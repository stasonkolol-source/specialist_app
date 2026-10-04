// Профили и пороги нагрузочного прогона (DEVELOPMENT_PLAN 8.3). Всё настраивается переменными
// окружения k6 (`-e ИМЯ=…`, их передаёт make loadtest); порядок прогона — docs/loadtest/README.md.

const env = (name, fallback) => (__ENV[name] === undefined || __ENV[name] === '' ? fallback : __ENV[name]);

export const BASE_URL = env('BASE_URL', 'http://host.docker.internal:8000').replace(/\/$/, '');
export const API = `${BASE_URL}/api/v1`;
export const PROFILE = env('PROFILE', 'smoke');
export const CITY = env('CITY', 'novi-sad');
export const USERS_FILE = env('USERS_FILE', '');
/** Пиковый RPS через 12 месяцев (ARCHITECTURE §2.3: 30–60); прогон доходит до ×2. */
export const PEAK_RPS = Number(env('PEAK_RPS', '60'));
/** Сколько пользователей входит в setup() и делит между собой запросы сценариев. */
export const POOL = Number(env('POOL', '60'));
/** Вход — не чаще лимита `/auth/*` на IP (10 в минуту, §13.3): весь прогон идёт с одного адреса. */
export const LOGINS_PER_MINUTE = Number(env('LOGINS_PER_MINUTE', '9'));
/** Сколько держать каждую ступень нагрузки (1× и 2× пика). */
export const HOLD = env('HOLD', '5m');
/** Добавка к порогам на сеть до stage, мс: k6 меряет у себя, SLO §2.4 — на сервере. */
export const NET_MS = Number(env('NET_MS', '0'));

// Доли сценариев в общем RPS — [Допущение] о смеси запросов Mini App: каталог и лента —
// основное, поллинг диалога (раз в 4 с, пока открыт S30) и бейджи (раз в минуту) — фон.
const SHARES = { catalog: 0.4, feed: 0.25, chat: 0.17, notifications: 0.17 };
/** Отклики: 1–3 тыс. в день через год (§2.3) — доли RPS, а не проценты; ×2 на пике. */
const RESPOND_RPS = Number(env('RESPOND_RPS', '0.2'));

export const ALL_SCENARIOS = ['login', 'catalog', 'feed', 'respond', 'chat', 'notifications'];
/** Без входа (локальный smoke): гостевые чтения, ничего не пишется. */
export const GUEST_SCENARIOS = ['catalog', 'feed'];

function selected(defaults) {
  const asked = env('SCENARIO', '');
  if (!asked) return defaults;
  const names = asked.split(',').map((s) => s.trim()).filter(Boolean);
  const unknown = names.filter((n) => !ALL_SCENARIOS.includes(n));
  if (unknown.length) throw new Error(`SCENARIO: неизвестные ${unknown.join(', ')}; есть ${ALL_SCENARIOS.join(', ')}`);
  return names;
}

function rampTo(rps) {
  // ступени: 1× пика → держим → 2× пика → держим → спад; rate — запросов в секунду
  const one = Math.max(1, Math.round(rps));
  return [
    { target: one, duration: '2m' },
    { target: one, duration: HOLD },
    { target: one * 2, duration: '2m' },
    { target: one * 2, duration: HOLD },
    { target: 0, duration: '1m' },
  ];
}

function arrival(exec, rps, maxVUs) {
  return {
    executor: 'ramping-arrival-rate',
    exec,
    startRate: 0,
    timeUnit: '1s',
    preAllocatedVUs: Math.max(2, Math.ceil(maxVUs / 2)),
    maxVUs,
    stages: rampTo(rps),
  };
}

function loadScenarios(names) {
  const all = {
    login: {
      executor: 'constant-arrival-rate',
      exec: 'login',
      rate: LOGINS_PER_MINUTE,
      timeUnit: '1m',
      duration: totalDuration(),
      preAllocatedVUs: 1,
      maxVUs: 2,
    },
    catalog: arrival('catalog', PEAK_RPS * SHARES.catalog, 40),
    feed: arrival('feed', PEAK_RPS * SHARES.feed, 25),
    respond: {
      executor: 'ramping-arrival-rate',
      exec: 'respond',
      startRate: 0,
      timeUnit: '10s',
      preAllocatedVUs: 1,
      maxVUs: 4,
      stages: rampTo(RESPOND_RPS * 10),
    },
    chat: arrival('chat', PEAK_RPS * SHARES.chat, 20),
    notifications: arrival('notifications', PEAK_RPS * SHARES.notifications, 20),
  };
  return Object.fromEntries(names.map((n) => [n, all[n]]));
}

function smokeScenarios(names) {
  // Мак владельца: не больше 2 VU и 30 с, только гостевые чтения (бриф 8.3)
  return Object.fromEntries(
    names.map((n) => [n, { executor: 'constant-vus', exec: `${n}Guest`, vus: 1, duration: '30s' }]),
  );
}

export function totalDuration() {
  const seconds = (d) => {
    const m = /^(\d+)(s|m|h)$/.exec(d);
    if (!m) throw new Error(`HOLD: длительность вида 30s, 5m, 1h — получено ${d}`);
    return Number(m[1]) * { s: 1, m: 60, h: 3600 }[m[2]];
  };
  return `${2 * 60 + seconds(HOLD) + 2 * 60 + seconds(HOLD) + 60}s`;
}

export function scenarios() {
  if (PROFILE === 'smoke') {
    const names = selected(GUEST_SCENARIOS);
    const bad = names.filter((n) => !GUEST_SCENARIOS.includes(n));
    if (bad.length) throw new Error(`smoke — только гостевые чтения (${GUEST_SCENARIOS.join(', ')}), не ${bad.join(', ')}`);
    return smokeScenarios(names.slice(0, 2));
  }
  if (PROFILE === 'load') return loadScenarios(selected(ALL_SCENARIOS));
  throw new Error(`PROFILE: smoke или load, получено ${PROFILE}`);
}

// Пороги = SLO ARCHITECTURE §2.4. `slo:api` — все запросы API, кроме поиска; `slo:search` —
// выдача и подсказки каталога. Пустые пороги групп (`p(95)>=0`) ничего не проверяют: они нужны,
// чтобы итог показал цифры по каждой группе эндпоинтов.
export const GROUPS = ['auth', 'catalog', 'search', 'feed', 'respond', 'chat', 'notifications'];

export function thresholds() {
  const t = {
    'http_req_duration{slo:api}': [`p(95)<${150 + NET_MS}`, `p(99)<${400 + NET_MS}`],
    'http_req_duration{slo:search}': [`p(95)<${200 + NET_MS}`, `p(99)<${400 + NET_MS}`],
    http_req_failed: ['rate<0.001'],
    checks: ['rate>0.999'],
  };
  for (const g of GROUPS) t[`http_req_duration{ep:${g}}`] = ['p(95)>=0'];
  return t;
}
