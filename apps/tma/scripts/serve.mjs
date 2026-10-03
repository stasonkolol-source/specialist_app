// Статический сервер собранного Mini App для Playwright: без зависимостей (работает в Docker-образе),
// применяет dist/_headers по путям, как Cloudflare (CSP — всем, «immutable» — только /assets/*, HTML
// — no-cache), сжимает текст gzip (как Cloudflare — иначе замер холодного старта качал бы втрое
// больше), неизвестный путь без расширения → index.html.
import { createReadStream, readFileSync, statSync } from 'node:fs';
import { createServer } from 'node:http';
import { extname, join, normalize } from 'node:path';
import { createGzip } from 'node:zlib';

const [dir = 'dist', port = '4174'] = process.argv.slice(2);
const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.woff2': 'font/woff2',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.json': 'application/json',
};

/** Правила _headers: строка пути (`/*`, `/assets/*`, `/`) и под ней строки «  Имя: значение» —
 *  подмножество формата, которое пишет сборка. */
function parseHeaders(path) {
  let text;
  try {
    text = readFileSync(path, 'utf8');
  } catch {
    return [];
  }
  const rules = [];
  for (const line of text.split('\n')) {
    if (/^\S/.test(line)) rules.push({ pattern: line.trim(), headers: [] });
    else if (/^\s+\S+:/.test(line) && rules.length > 0) {
      const [name, ...value] = line.trim().split(':');
      rules.at(-1).headers.push([name, value.join(':').trim()]);
    }
  }
  return rules;
}

/** `*` в конце — любой хвост пути, иначе — точное совпадение (как splat у Cloudflare). */
const matches = (pattern, path) =>
  pattern.endsWith('*') ? path.startsWith(pattern.slice(0, -1)) : path === pattern;

const rules = parseHeaders(join(dir, '_headers'));
const headersFor = (path) =>
  Object.fromEntries(
    rules.filter((rule) => matches(rule.pattern, path)).flatMap((rule) => rule.headers),
  );
const COMPRESSIBLE = new Set(['.html', '.js', '.css', '.svg', '.json']);

createServer((req, res) => {
  const path = normalize(decodeURIComponent(new URL(req.url ?? '/', 'http://x').pathname)).replace(
    /^(\.\.[/\\])+/,
    '',
  );
  let file = join(dir, path);
  try {
    if (statSync(file).isDirectory()) file = join(file, 'index.html');
    statSync(file);
  } catch {
    if (extname(path)) {
      res.writeHead(404).end();
      return;
    }
    file = join(dir, 'index.html');
  }
  const gzip =
    COMPRESSIBLE.has(extname(file)) && /\bgzip\b/.test(String(req.headers['accept-encoding']));
  res.writeHead(200, {
    'content-type': TYPES[extname(file)] ?? 'application/octet-stream',
    ...(gzip ? { 'content-encoding': 'gzip', vary: 'Accept-Encoding' } : {}),
    ...headersFor(path),
  });
  const stream = createReadStream(file);
  (gzip ? stream.pipe(createGzip()) : stream).pipe(res);
}).listen(Number(port), '127.0.0.1');
