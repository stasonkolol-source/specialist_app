// Нагрузочный прогон «Соседей» (DEVELOPMENT_PLAN 8.3): k6 в Docker, без npm-зависимостей.
// Сценарии — как ходит Mini App: вход, каталог и поиск, лента заявок, отклик, поллинг диалога по
// ETag, уведомления и бейджи. Запуск — make loadtest ENV=local|stage (make/loadtest.mk), порядок
// и шаблон отчёта — docs/loadtest/README.md.
//
// Пользователи — демо-специалисты `seed-demo --scale lab`: initData для них печатает
// `cli loadtest-initdata` (подпись токеном бота окружения, годен час). setup() входит под первыми
// POOL из них не чаще лимита `/auth/*` на IP, дальше каждый запрос берёт случайного: лимиты
// каталога и ленты (120 в минуту на пользователя, §13.3) делятся на весь пул. Остальные
// initData — сценарию login: он меряет сам вход, не упираясь в лимит 30 в час на человека.
import http from 'k6/http';
import { check, fail, sleep } from 'k6';
import exec from 'k6/execution';
import { Counter } from 'k6/metrics';
import { SharedArray } from 'k6/data';

import {
  API,
  BASE_URL,
  CITY,
  LOGINS_PER_MINUTE,
  POOL,
  PROFILE,
  USERS_FILE,
  scenarios,
  thresholds,
  totalDuration,
} from './config.js';

export const options = {
  scenarios: scenarios(),
  thresholds: thresholds(),
  setupTimeout: '20m',
  summaryTrendStats: ['avg', 'med', 'p(95)', 'p(99)', 'max', 'count'],
  userAgent: 'sosed-loadtest/8.3 (k6)',
  discardResponseBodies: false,
};

const users = new SharedArray('users', () => (USERS_FILE ? JSON.parse(open(USERS_FILE)) : []));
const responded = new Counter('respond_created');
const refused = new Counter('respond_refused');

const QUERIES = ['электрик', 'сантехник', 'уборка', 'маникюр', 'ремонт', 'vodoinstalater', 'frizer', 'čišćenje', 'masaža', 'репетитор', 'элктрик'];
const SUGGEST = ['эле', 'сан', 'убо', 'vod', 'fri', 'čiš', 'рем', 'mas'];
const LANG = { 'Accept-Language': 'ru' };
// бизнес-отказ отклика — не ошибка сервера: место кончилось, уже откликался, суточная квота,
// заявку закрыли между выборкой и откликом
const RESPOND_OK = http.expectedStatuses(201, 404, 409, 429);

const pick = (items) => items[Math.floor(Math.random() * items.length)];
const tags = (name, ep, slo) => (slo ? { name, ep, slo } : { name, ep });

function get(path, name, ep, slo, headers = {}) {
  return http.get(`${API}${path}`, { headers: { ...LANG, ...headers }, tags: tags(name, ep, slo) });
}

function bearer(token) {
  return { Authorization: `Bearer ${token}` };
}

function uuid4() {
  // Idempotency-Key отклика; криптостойкость не нужна
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = Math.floor(Math.random() * 16);
    return (c === 'x' ? r : (r % 4) + 8).toString(16);
  });
}

function signIn(initData, extraTags = {}) {
  return http.post(`${API}/auth/telegram`, null, {
    headers: { ...LANG, Authorization: `tma ${initData}` },
    tags: { name: 'POST /auth/telegram', ep: 'auth', slo: 'api', ...extraTags },
    responseCallback: http.expectedStatuses(200, 429),
  });
}

// --- setup: город, справочники и пул вошедших пользователей -------------------------------------

function discover() {
  const cities = get('/cities', 'GET /cities', 'setup');
  if (cities.status !== 200) fail(`GET /cities → ${cities.status}: API ${BASE_URL} недоступен?`);
  const city = cities.json().find((c) => c.slug === CITY);
  if (!city) fail(`город ${CITY} не найден: CITY=<slug>`);
  const categoryIds = [];
  const walk = (nodes) => nodes.forEach((n) => { categoryIds.push(n.id); walk(n.children || []); });
  walk(get('/categories', 'GET /categories', 'setup').json());
  const profiles = get(`/specialists?city_id=${city.id}&limit=50`, 'GET /specialists', 'setup').json().items.map((s) => s.profile_id);
  const jobs = [];
  let cursor = null;
  for (let page = 0; page < 4; page += 1) {
    const q = `/jobs?city_id=${city.id}&limit=50${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`;
    const body = get(q, 'GET /jobs', 'setup').json();
    jobs.push(...body.items.map((j) => j.id));
    cursor = body.next_cursor;
    if (!cursor) break;
  }
  if (!profiles.length || !jobs.length) {
    console.warn(`мало данных: ${profiles.length} профилей, ${jobs.length} заявок — нужен seed-demo --scale lab`);
  }
  return { cityId: city.id, categoryIds, profiles, jobs };
}

function signInPool(size) {
  // не чаще LOGINS_PER_MINUTE: лимит /auth/* — 10 в минуту на IP, а весь прогон — с одного адреса
  const pause = 60 / LOGINS_PER_MINUTE;
  const pool = [];
  let earliestExpiry = Infinity;
  let fresh = 0;
  for (let i = 0; i < size; i += 1) {
    let res = signIn(users[i]);
    while (res.status === 429) {
      sleep(Number(res.headers['Retry-After'] || pause));
      res = signIn(users[i]);
    }
    if (res.status !== 200) fail(`вход пользователя ${i} → ${res.status}: initData старше часа или не тот бот?`);
    const body = res.json();
    if (body.is_new) fresh += 1;
    pool.push(body.access_token);
    earliestExpiry = Math.min(earliestExpiry, Date.parse(body.access_expires_at));
    if (i + 1 < size) sleep(pause);
  }
  if (fresh) console.warn(`${fresh} из ${size} вошли впервые: демо-специалистов нет — seed-demo --scale lab`);
  return { pool, earliestExpiry };
}

export function setup() {
  const world = discover();
  if (PROFILE === 'smoke') return { ...world, pool: [] };
  const reserve = users.length - POOL;
  if (POOL < 1 || reserve < 5) {
    fail(`нужно initData на POOL + 5 пользователей (${POOL + 5}), в USERS_FILE — ${users.length}: make loadtest-users`);
  }
  const { pool, earliestExpiry } = signInPool(POOL);
  // access живёт JWT_ACCESS_TTL_SECONDS (900 с); обновлять его k6 не умеет без гонок refresh
  // между VU, поэтому прогон должен уложиться в срок самого раннего токена
  const end = Date.now() + Number(totalDuration().slice(0, -1)) * 1000;
  if (end > earliestExpiry) {
    fail(
      `токены пула истекут до конца прогона (${new Date(earliestExpiry).toISOString()}): на время ` +
        'прогона JWT_ACCESS_TTL_SECONDS=3600 на stage или короче HOLD (docs/loadtest/README.md)',
    );
  }
  return { ...world, pool };
}

// --- сценарии под нагрузкой ---------------------------------------------------------------------

const etags = {};
const inbox = {};

function asUser(data) {
  const i = Math.floor(Math.random() * data.pool.length);
  return { i, headers: bearer(data.pool[i]) };
}

function searchQuery(data) {
  const roll = Math.random();
  if (roll < 0.4) return `?city_id=${data.cityId}&q=${encodeURIComponent(pick(QUERIES))}&limit=20`;
  if (roll < 0.8) return `?city_id=${data.cityId}&category_id=${pick(data.categoryIds)}&limit=20`;
  return `?city_id=${data.cityId}&limit=20&available_today=true`;
}

function catalogRequest(data, headers) {
  // выдача и счётчик фильтров — поиск (§2.4: p95 < 200 мс), карточка и справочник — обычный API
  const roll = Math.random();
  let res;
  if (roll < 0.5) {
    res = get(`/specialists${searchQuery(data)}`, 'GET /specialists', 'search', 'search', headers);
  } else if (roll < 0.62) {
    res = get(`/specialists/count${searchQuery(data)}`, 'GET /specialists/count', 'search', 'search', headers);
  } else if (roll < 0.75) {
    res = get(`/suggest?q=${encodeURIComponent(pick(SUGGEST))}`, 'GET /suggest', 'search', 'search', headers);
  } else if (roll < 0.95 && data.profiles.length) {
    res = get(`/specialists/${pick(data.profiles)}`, 'GET /specialists/{id}', 'catalog', 'api', headers);
  } else {
    res = get('/categories', 'GET /categories', 'catalog', 'api', headers);
  }
  check(res, { 'catalog 200': (r) => r.status === 200 || r.status === 304 });
}

function feedRequest(data, headers) {
  const roll = Math.random();
  let res;
  if (roll < 0.6) {
    const category = Math.random() < 0.5 ? `&category=${pick(data.categoryIds)}` : '';
    res = get(`/jobs?city_id=${data.cityId}&limit=20${category}`, 'GET /jobs', 'feed', 'api', headers);
  } else if (roll < 0.75) {
    res = get(`/jobs/count?city_id=${data.cityId}&new_hours=24`, 'GET /jobs/count', 'feed', 'api', headers);
  } else if (data.jobs.length) {
    res = get(`/jobs/${pick(data.jobs)}`, 'GET /jobs/{id}', 'feed', 'api', headers);
  } else {
    return;
  }
  check(res, { 'feed 200': (r) => r.status === 200 });
}

export function login() {
  // свои пользователи, не из пула: у каждого лимит 30 входов в час (§13.3)
  const reserve = users.length - POOL;
  const res = signIn(users[POOL + (exec.scenario.iterationInTest % reserve)]);
  check(res, { 'login 200': (r) => r.status === 200 });
}

export function catalog(data) {
  catalogRequest(data, asUser(data).headers);
}

export function feed(data) {
  feedRequest(data, asUser(data).headers);
}

export function respond(data) {
  if (!data.jobs.length) return;
  const { headers } = asUser(data);
  const res = http.post(
    `${API}/jobs/${pick(data.jobs)}/responses`,
    JSON.stringify({ message: 'Могу сделать на этой неделе, детали обсудим в чате.', price_type: 'negotiable' }),
    {
      headers: { ...LANG, ...headers, 'Content-Type': 'application/json', 'Idempotency-Key': uuid4() },
      tags: { name: 'POST /jobs/{id}/responses', ep: 'respond', slo: 'api' },
      responseCallback: RESPOND_OK,
    },
  );
  (res.status === 201 ? responded : refused).add(1);
  check(res, { 'respond 201 or business refusal': (r) => [201, 404, 409, 429].includes(r.status) });
}

export function chat(data) {
  // S30 опрашивает последние сообщения раз в 4 с с If-None-Match — сервер отвечает 304;
  // список диалогов (S29) — при входе в раздел. Диалоги пользователя запоминаются в VU.
  const { i, headers } = asUser(data);
  const known = inbox[i];
  if (!known || (known.length && Math.random() < 0.1) || (!known.length && Math.random() < 0.3)) {
    const res = get('/conversations?limit=20', 'GET /conversations', 'chat', 'api', headers);
    check(res, { 'conversations 200': (r) => r.status === 200 });
    if (res.status === 200) inbox[i] = res.json().items.map((c) => c.id);
    return;
  }
  if (!known.length) return;
  const id = pick(known);
  const key = `${i}:${id}`;
  const res = get(
    `/conversations/${id}/messages?limit=50`,
    'GET /conversations/{id}/messages',
    'chat',
    'api',
    etags[key] ? { ...headers, 'If-None-Match': etags[key] } : headers,
  );
  check(res, { 'messages 200/304': (r) => r.status === 200 || r.status === 304 });
  if (res.headers.Etag) etags[key] = res.headers.Etag;
}

export function notifications(data) {
  const { headers } = asUser(data);
  const res =
    Math.random() < 0.7
      ? get('/me/badges', 'GET /me/badges', 'notifications', 'api', headers)
      : get('/me/notifications?limit=20', 'GET /me/notifications', 'notifications', 'api', headers);
  check(res, { 'notifications 200': (r) => r.status === 200 });
}

// --- smoke: гостем, только чтение, с паузами (Мак владельца) ------------------------------------

export function catalogGuest(data) {
  catalogRequest(data, {});
  sleep(1 + Math.random());
}

export function feedGuest(data) {
  feedRequest(data, {});
  sleep(1 + Math.random());
}

// --- итог: короткий текст в консоль и полный JSON в results/ --------------------------------------

function fmt(v) {
  return v === undefined ? '—' : `${v.toFixed(1)}`;
}

export function handleSummary(data) {
  const lines = [`Соседи 8.3 · ${PROFILE} · ${BASE_URL}`, ''];
  const m = data.metrics;
  const reqs = m.http_reqs ? m.http_reqs.values : { count: 0, rate: 0 };
  lines.push(`запросов ${reqs.count}, ${fmt(reqs.rate)} RPS; ошибок ${((m.http_req_failed ? m.http_req_failed.values.rate : 0) * 100).toFixed(3)}%`);
  lines.push('', 'группа            p95 мс   p99 мс   max мс   запросов');
  for (const name of Object.keys(m).sort()) {
    const g = /^http_req_duration\{(ep|slo):(\w+)\}$/.exec(name);
    if (!g) continue;
    const v = m[name].values;
    lines.push(`${`${g[1]}:${g[2]}`.padEnd(16)}  ${fmt(v['p(95)']).padStart(7)}  ${fmt(v['p(99)']).padStart(7)}  ${fmt(v.max).padStart(7)}  ${String(v.count || 0).padStart(9)}`);
  }
  if (m.respond_created || m.respond_refused) {
    lines.push('', `отклики: создано ${m.respond_created ? m.respond_created.values.count : 0}, бизнес-отказ ${m.respond_refused ? m.respond_refused.values.count : 0}`);
  }
  lines.push('', 'пороги SLO (§2.4):');
  let ok = true;
  for (const [name, metric] of Object.entries(m)) {
    for (const [rule, result] of Object.entries(metric.thresholds || {})) {
      if (rule === 'p(95)>=0') continue;
      ok = ok && result.ok;
      lines.push(`  ${result.ok ? 'OK  ' : 'FAIL'} ${name} ${rule}`);
    }
  }
  lines.push('', ok ? 'SLO выполнены' : 'SLO НЕ выполнены', '');
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  return {
    stdout: lines.join('\n'),
    [`results/${PROFILE}-${stamp}.json`]: JSON.stringify(data, null, 2),
  };
}
