// Статический сервер собранного Mini App для Playwright: без зависимостей (работает в Docker-образе),
// применяет dist/_headers (CSP, как на Cloudflare), сжимает текст gzip (как Cloudflare — иначе
// замер холодного старта качал бы втрое больше), неизвестный путь без расширения → index.html.
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

/** `/*` и строки «  Имя: значение» — подмножество формата _headers, которое пишет сборка. */
function parseHeaders(path) {
  try {
    return readFileSync(path, 'utf8')
      .split('\n')
      .filter((line) => /^\s+\S+:/.test(line))
      .map((line) => {
        const [name, ...value] = line.trim().split(':');
        return [name, value.join(':').trim()];
      });
  } catch {
    return [];
  }
}

const headers = parseHeaders(join(dir, '_headers'));
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
    ...Object.fromEntries(headers),
  });
  const stream = createReadStream(file);
  (gzip ? stream.pipe(createGzip()) : stream).pipe(res);
}).listen(Number(port), '127.0.0.1');
