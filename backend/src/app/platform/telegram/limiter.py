"""Лимитер отправки бота в Valkey (ARCHITECTURE §11.2, §12.2): 25 msg/s и 1 msg/s на чат.

Лимиты Bot API — на бота и на чат, а воркеров несколько: состояние общее, в Valkey. Слот
(модель GCRA, bucket.py) занимается сразу в обоих бакетах одним Lua-скриптом: атомарно, без
повторов между воркерами; время — часы Valkey (`TIME`), одни на всех. Слот дальше горизонта
не занимается: такое сообщение вернётся ближе к сроку, а не займёт место впереди тех, кто
придёт раньше него. После 429 Telegram все слоты начинаются после паузы (она только
удлиняется).

Valkey недоступен — отправка идёт без лимитера (fail open) с предупреждением в логе: лишнее
притормозит сам Telegram ответом 429, а уведомления не встанут.
"""

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.platform.telegram.bucket import Bucket
from app.platform.telegram.port import Slot

log = structlog.get_logger(__name__)

BOT_BUCKET = Bucket(rate=25.0, capacity=25.0)
"""Рассылка бота: ≈30 msg/s у Telegram, берём с запасом."""
CHAT_BUCKET = Bucket(rate=1.0, capacity=1.0)
"""Одному чату — не чаще раза в секунду."""

RESERVE = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
local bot_interval, bot_tolerance = tonumber(ARGV[1]), tonumber(ARGV[2])
local chat_interval, chat_tolerance = tonumber(ARGV[3]), tonumber(ARGV[4])
local within = tonumber(ARGV[5])
local bot_tat = tonumber(redis.call('GET', KEYS[1]) or '0')
local chat_tat = tonumber(redis.call('GET', KEYS[2]) or '0')
local paused = tonumber(redis.call('GET', KEYS[3]) or '0')
local bot_at = math.max(now, paused, bot_tat - bot_tolerance)
local chat_at = math.max(now, paused, chat_tat - chat_tolerance)
local function advance(key, tat, at, interval)
  local next_tat = math.max(tat, at) + interval
  redis.call('SET', KEYS[key], tostring(next_tat), 'PX', math.ceil((next_tat - now) * 1000) + 1000)
end
if chat_at <= bot_at then
  if bot_at - now > within then
    return {tostring(bot_at - now), '0', '0'}
  end
  advance(1, bot_tat, bot_at, bot_interval)
  advance(2, chat_tat, bot_at, chat_interval)
  return {tostring(bot_at - now), '1', '0'}
end
if chat_at - now > within then
  return {tostring(chat_at - now), '0', '0'}
end
advance(2, chat_tat, chat_at, chat_interval)
return {tostring(chat_at - now), '1', '1'}
"""
"""Занять слот (earliest()/advance() в bucket.py), если он не дальше горизонта. Держит бот —
слот сразу в обоих бакетах. Держит чат — только слот чата: слот бота займётся в момент
отправки (RESERVE_BOT), иначе сообщение, ждущее секунду из-за своего чата, сдвинуло бы
очередь всего бота. Ответ — ожидание строкой (числа из Lua Valkey округлил бы до целых),
«занят» и «ещё слот бота»."""

RESERVE_BOT = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
local interval, tolerance, within = tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3])
local tat = tonumber(redis.call('GET', KEYS[1]) or '0')
local paused = tonumber(redis.call('GET', KEYS[2]) or '0')
local at = math.max(now, paused, tat - tolerance)
if at - now > within then
  return {tostring(at - now), '0'}
end
local next_tat = math.max(tat, at) + interval
redis.call('SET', KEYS[1], tostring(next_tat), 'PX', math.ceil((next_tat - now) * 1000) + 1000)
return {tostring(at - now), '1'}
"""

PAUSE = """
local clock = redis.call('TIME')
local until_ = tonumber(clock[1]) + tonumber(clock[2]) / 1000000 + tonumber(ARGV[1])
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
if until_ > current then
  redis.call('SET', KEYS[1], tostring(until_), 'PX', math.ceil(tonumber(ARGV[1]) * 1000) + 1000)
end
return 1
"""


class ValkeySendLimiter:
    def __init__(
        self,
        valkey: Redis,
        *,
        prefix: str = "tg:send",
        bot: Bucket = BOT_BUCKET,
        chat: Bucket = CHAT_BUCKET,
    ) -> None:
        self._prefix = prefix
        self._bot, self._chat = bot, chat
        self._reserve = valkey.register_script(RESERVE)
        self._reserve_bot = valkey.register_script(RESERVE_BOT)
        self._pause = valkey.register_script(PAUSE)

    async def reserve(self, chat_id: int, *, within: float) -> Slot:
        keys = [self._bot_key, f"{self._prefix}:chat:{chat_id}", self._pause_key]
        args = [
            self._bot.interval,
            self._bot.tolerance,
            self._chat.interval,
            self._chat.tolerance,
            within,
        ]
        try:
            wait, reserved, bot_pending = await self._reserve(keys=keys, args=args)
        except RedisError as exc:
            log.warning("telegram_limiter_unavailable", error=type(exc).__name__)
            return Slot(wait=0.0, reserved=True)
        return Slot(wait=float(wait), reserved=reserved == b"1", bot_pending=bot_pending == b"1")

    async def reserve_bot(self, *, within: float) -> Slot:
        keys = [self._bot_key, self._pause_key]
        try:
            wait, reserved = await self._reserve_bot(
                keys=keys, args=[self._bot.interval, self._bot.tolerance, within]
            )
        except RedisError as exc:
            log.warning("telegram_limiter_unavailable", error=type(exc).__name__)
            return Slot(wait=0.0, reserved=True)
        return Slot(wait=float(wait), reserved=reserved == b"1")

    async def pause(self, seconds: float) -> None:
        try:
            await self._pause(keys=[self._pause_key], args=[seconds])
        except RedisError as exc:
            log.warning("telegram_limiter_unavailable", error=type(exc).__name__)

    @property
    def _bot_key(self) -> str:
        return f"{self._prefix}:bot"

    @property
    def _pause_key(self) -> str:
        return f"{self._prefix}:pause"
