// pnpm -F design-tokens check:contrast — таблица контраста пар токенов в обеих темах.
import source from '../tokens.json' with { type: 'json' };
import { checkContrast } from '../src/contrast.ts';

const results = checkContrast(source);
for (const r of results) {
  const mark = r.ok ? 'ok  ' : 'FAIL';
  const pair = `${r.fg} / ${[...(r.over ?? []), r.bg].join('+')}`.padEnd(34);
  console.log(`${mark} ${r.theme.padEnd(5)} ${pair} ${r.ratio.toFixed(2).padStart(5)} ≥ ${r.min}  ${r.use}`);
}

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} пар проходят`);
if (failed.length > 0) process.exit(1);
