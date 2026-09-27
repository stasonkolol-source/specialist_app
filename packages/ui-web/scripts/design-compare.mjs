// make design-compare [GREP=S03] — отчёт «эталон рядом с фактом»: PNG артборда из design/reference
// и скриншоты реализации. Факты: галерея ui-web ↔ Main (эталон галереи), экраны apps/tma ↔ артборд
// по коду экрана в имени файла (S03-…, D30-…). Сеть и зависимости не нужны: открывается как файл.
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { relative, resolve } from 'node:path';

const ROOT = resolve(import.meta.dirname, '../../..');
const REF = `${ROOT}/design/reference`;
const OUT = `${ROOT}/packages/ui-web/test-results/design-compare`;
const grep = process.argv[2] ? new RegExp(process.argv[2], 'i') : null;

const pngs = (dir) =>
  existsSync(dir)
    ? readdirSync(dir)
        .filter((f) => f.endsWith('.png'))
        .sort()
    : [];
const boards = JSON.parse(readFileSync(`${ROOT}/design/project/canvas.json`, 'utf8')).boards;

const galleryFacts = pngs(`${ROOT}/packages/ui-web/e2e/__screenshots__`)
  .filter((f) => f.endsWith('-light-ru.png'))
  .map((f) => `${ROOT}/packages/ui-web/e2e/__screenshots__/${f}`);
const screenDir = `${ROOT}/apps/tma/e2e/__screenshots__`;
const screenFacts = pngs(screenDir).map((f) => `${screenDir}/${f}`);

const entries = [
  {
    code: 'Main',
    title: boards['Main.dc.html']?.title ?? 'Main',
    ref: `${REF}/gallery/Main.png`,
    facts: galleryFacts,
  },
  ...pngs(REF).map((file) => {
    const base = file.replace(/\.png$/, '');
    const code = base.split('-')[0];
    return {
      code,
      title: boards[`${base}.dc.html`]?.title ?? base,
      ref: `${REF}/${file}`,
      facts: screenFacts.filter((f) => /^[A-Z]\d+[a-z]?/.exec(f.split('/').at(-1))?.[0] === code),
    };
  }),
].filter((e) => !grep || grep.test(`${e.code} ${e.title}`));

const esc = (s) =>
  s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
const img = (path) =>
  `<figure><img src="${esc(relative(OUT, path))}" alt="" loading="lazy"><figcaption>${esc(relative(ROOT, path))}</figcaption></figure>`;

const cards = entries.map(
  (e) => `<section><h2>${esc(e.title)}</h2><div class="row">
<div class="col"><h3>Эталон</h3>${existsSync(e.ref) ? img(e.ref) : '<p class="miss">нет эталона: make design-render</p>'}</div>
<div class="col"><h3>Факт (${e.facts.length})</h3>${e.facts.length ? e.facts.map(img).join('') : '<p class="miss">скриншотов реализации пока нет</p>'}</div>
</div></section>`,
);

mkdirSync(OUT, { recursive: true });
writeFileSync(
  `${OUT}/index.html`,
  `<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Эталон рядом с фактом</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{color-scheme:light dark;--bg:#F2F3F5;--card:#FFFFFF;--text:#111418;--muted:#5B6270}
@media (prefers-color-scheme:dark){:root{--bg:#0E1621;--card:#1E2A36;--text:#F2F5F8;--muted:#9AA8B6}}
body{margin:0;padding:16px;background:var(--bg);color:var(--text);font:15px/22px system-ui,sans-serif}
section{background:var(--card);border-radius:16px;padding:16px;margin:0 0 16px}
h2{margin:0 0 12px;font-size:17px}h3{margin:0 0 8px;font-size:13px;color:var(--muted);text-transform:uppercase}
.row{display:flex;gap:24px;align-items:flex-start;overflow-x:auto}.col{flex:none}
.col:last-child{display:flex;flex-direction:column;gap:12px}
figure{margin:0}img{display:block;max-width:100%;border:1px solid color-mix(in srgb,var(--muted) 30%,transparent)}
figcaption{font-size:12px;color:var(--muted)}.miss{color:var(--muted)}
</style></head><body><h1>Эталон рядом с фактом · ${entries.length}</h1>${cards.join('\n')}</body></html>
`,
);
console.log(`${entries.length} эталон(ов) → ${relative(ROOT, OUT)}/index.html`);
