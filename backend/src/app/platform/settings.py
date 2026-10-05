"""Настройки всех процессов (ADR-0020 §10): группы pydantic-settings с env_prefix.

Правила:
- Настройки читаются только здесь. Остальной код получает группы через DI (Scope.APP),
  а application — frozen dataclass `<Модуль>Config`, собранный в di.py модуля.
- Секреты — `SecretStr`: в repr и логах их значения не видны.
- Переменные окружения важнее `backend/.env`. Путь к `.env` абсолютный от этого файла,
  поэтому `.env` находится из любого рабочего каталога.
- Новая настройка появляется в `backend/.env.example` в том же шаге (это проверяет тест).
"""

import base64
import os
import re
from datetime import date
from enum import StrEnum
from ipaddress import IPv4Network, IPv6Network, ip_network
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import (
    AliasChoices,
    Field,
    IPvAnyNetwork,
    SecretStr,
    ValidationError,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
KAMAL_VERSION = "KAMAL_VERSION"
"""Версия образа: Kamal передаёт её каждому контейнеру приложения (kamal/commands/app.rb)."""


_TELEGRAM_USERNAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{4,31}")
"""Имя пользователя Telegram: 5–32 символа, начинается с буквы."""

_WEBHOOK_SECRET = re.compile(r"[A-Za-z0-9_-]{32,256}")
"""secret_token webhook: алфавит и предел 256 — Bot API (setWebhook); от 32 символов — наше
требование: секрет — единственная защита адреса, его подбирают (`make gen-secret` даёт 64)."""

_HEX_KEY = re.compile(r"[0-9a-fA-F]{64}")
_BASE64_KEY = re.compile(r"[A-Za-z0-9_-]{43}=?")


def key_bytes(value: SecretStr) -> bytes:
    """Ключ шифрования из настройки — ровно 32 байта: hex (`make gen-secret`, 64 знака) или
    base64url (`secrets.token_urlsafe(32)`, 43 знака). Иное — ValueError: пароль ключом не
    станет."""
    text = value.get_secret_value().strip()
    if _HEX_KEY.fullmatch(text):
        return bytes.fromhex(text)
    if _BASE64_KEY.fullmatch(text):
        return base64.urlsafe_b64decode(text.rstrip("=") + "=")
    raise ValueError("key must be 32 bytes: 64 hex characters (make gen-secret) or base64url")


PRIVATE_NETWORKS: tuple[IPv4Network | IPv6Network, ...] = tuple(
    ip_network(cidr)
    for cidr in (
        "127.0.0.0/8",
        "::1/128",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "fc00::/7",
    )
)
"""Loopback и частные сети: сеть контейнеров Kamal и private network Hetzner. Снаружи из них
не подключиться — web не опубликован, наружу смотрит только kamal-proxy."""

CLOUDFLARE_IPS: tuple[IPv4Network | IPv6Network, ...] = tuple(
    ip_network(cidr)
    for cidr in (
        "173.245.48.0/20",
        "103.21.244.0/22",
        "103.22.200.0/22",
        "103.31.4.0/22",
        "141.101.64.0/18",
        "108.162.192.0/18",
        "190.93.240.0/20",
        "188.114.96.0/20",
        "197.234.240.0/22",
        "198.41.128.0/17",
        "162.158.0.0/15",
        "104.16.0.0/13",
        "104.24.0.0/14",
        "172.64.0.0/13",
        "131.0.72.0/22",
        "2400:cb00::/32",
        "2606:4700::/32",
        "2803:f800::/32",
        "2405:b500::/32",
        "2405:8100::/32",
        "2a06:98c0::/29",
        "2c0f:f248::/32",
    )
)
"""Диапазоны края Cloudflare (cloudflare.com/ips-v4, ips-v6, сверено 2026-10). Меняются
редко; новые — через APP_CLOUDFLARE_IPS без релиза. Тот же список — в firewall origin (8.4)."""


class Environment(StrEnum):
    DEV = "dev"
    TEST = "test"
    STAGE = "stage"
    PRODUCTION = "production"


class UpdatesMode(StrEnum):
    """Как бот получает апдейты (ADR-0011): polling — dev; webhook — stage и prod."""

    POLLING = "polling"
    WEBHOOK = "webhook"


class SettingsError(RuntimeError):
    """Настройки неполны или неверны — процесс не должен стартовать."""


class _Group(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
        frozen=True,
    )


class AppSettings(_Group):
    model_config = SettingsConfigDict(env_prefix="APP_")

    env: Environment = Environment.DEV
    name: str = "Соседи"
    """Имя продукта в текстах сервера (`{{appName}}` правовых документов); для sr-Latn —
    транслитом. Код продукта остаётся specialist_app."""
    log_level: str = "INFO"
    log_json: bool = True
    release: str = Field(default_factory=lambda: os.environ.get(KAMAL_VERSION) or "dev")
    """Релиз в логах и Sentry: APP_RELEASE, иначе версия образа, которую Kamal кладёт
    в контейнер (KAMAL_VERSION), иначе dev."""
    web_host: str = "127.0.0.1"
    """Адрес HTTP-сервера процесса — uvicorn web или приём webhook бота (TELEGRAM_UPDATES):
    локально — только loopback; в контейнере — 0.0.0.0 (за kamal-proxy)."""
    web_port: int = Field(default=8000, ge=1, le=65535)
    trusted_proxies: list[IPvAnyNetwork] = Field(default_factory=lambda: list(PRIVATE_NETWORKS))
    """Свои обратные прокси (kamal-proxy в сети Docker, cloudflared на loopback): только от
    них web принимает X-Forwarded-For и X-Forwarded-Proto (ARCHITECTURE §13.3, шаг 8.4).
    JSON-список CIDR; по умолчанию — loopback и частные сети."""
    cloudflare_ips: list[IPvAnyNetwork] = Field(default_factory=lambda: list(CLOUDFLARE_IPS))
    """Адреса края Cloudflare (https://www.cloudflare.com/ips/): если к нашему прокси
    подключился край, адрес клиента берётся из CF-Connecting-IP. JSON-список CIDR."""
    api_public_url: str = "http://127.0.0.1:8000"
    """Публичный адрес API: из него строится `type` ошибок RFC 9457."""
    admin_public_url: str | None = None
    """Адрес админки для персонала, с `/admin`: ссылка «Открыть в админке» под карточкой кейса в
    чате модераторов (2.5b). Пусто — в dev APP_API_PUBLIC_URL + `/admin` (тот же процесс web), на
    stage и проде ссылки нет: админка там — на своём хосте за Access, `https://admin.<домен>/admin`
    (K31), его и прописывает деплой."""
    min_client_versions: dict[str, str] = Field(default_factory=dict)
    """Минимальные версии клиентов для 426, JSON: {"tma": "1.0.0"}. С 1.1 — из client-config."""
    hash_key: SecretStr | None = None
    """Ключ HMAC для хэшей способов входа удалённых аккаунтов (антифрод 12 месяцев, §7.10).
    Постоянный: смена ключа «забудет» все хэши. На stage и проде обязателен; в dev и тестах без
    него — фиксированный ключ разработки."""
    admin_session_key: SecretStr | None = None
    """Ключ подписи cookie сессии админки /admin (2.7a). Без него на stage и проде админка не
    монтируется (публикация — только за Cloudflare Access, K31); в dev и тестах — ключ
    разработки. Смена ключа завершает все сессии персонала."""
    totp_key: SecretStr | None = None
    """Ключ шифрования секретов TOTP персонала в БД (8.4): AES-256-GCM, 32 случайных байта — hex
    (`make gen-secret`) или base64url. На stage и проде с включённой админкой (есть
    APP_ADMIN_SESSION_KEY) обязателен; в dev и тестах без него — ключ разработки. Смена — только
    через APP_TOTP_KEY_PREVIOUS (infra/runbooks/secrets-rotation.md), иначе TOTP персонала
    придётся заводить заново."""
    totp_key_previous: SecretStr | None = None
    """Прежний APP_TOTP_KEY на время ротации: им только расшифровываем, удачный вход и
    `cli staff-totp-reencrypt` перешифровывают текущим. После перешифровки — убрать."""

    @field_validator("totp_key", "totp_key_previous")
    @classmethod
    def _key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            key_bytes(value)
        return value

    @field_validator("min_client_versions")
    @classmethod
    def _versions(cls, value: dict[str, str]) -> dict[str, str]:
        for platform, version in value.items():
            if not re.fullmatch(r"[a-z]+", platform) or not re.fullmatch(
                r"\d+(\.\d+){0,2}", version
            ):
                raise ValueError(f"bad min client version {platform}={version}")
        return value


class DbSettings(_Group):
    model_config = SettingsConfigDict(env_prefix="DB_")

    dsn: SecretStr
    migrator_dsn: SecretStr | None = None
    readonly_dsn: SecretStr | None = None
    """Роль readonly (ADR-0005) для отчётов ликвидности 6.6: свой statement_timeout 30 с и
    чтение без права записи на уровне роли. Пусто — основная роль в транзакции READ ONLY."""
    pool_size: int = Field(default=10, ge=1)
    pool_max_overflow: int = Field(default=5, ge=0)
    echo: bool = False


class ValkeySettings(_Group):
    model_config = SettingsConfigDict(env_prefix="VALKEY_")

    url: SecretStr


class TelegramSettings(_Group):
    model_config = SettingsConfigDict(env_prefix="TELEGRAM_")

    bot_token: SecretStr
    bot_username: str
    updates: UpdatesMode = UpdatesMode.POLLING
    """Приём апдейтов процессом bot. webhook (stage, prod) — aiohttp-сервер на APP_WEB_HOST и
    APP_WEB_PORT за kamal-proxy, адрес — TELEGRAM_WEBHOOK_BASE_URL + /integrations/telegram/webhook;
    нужен TELEGRAM_WEBHOOK_SECRET. Задаётся явно в Kamal, а не выводится из APP_ENV: откат на
    polling — без смены окружения (в Kamal — вместе с `proxy: false` у роли bot: polling не
    отвечает на /up, 0.25e)."""
    webhook_base_url: str | None = None
    """Схема и хост, на которые Telegram шлёт webhook, без пути: свой хост процесса bot
    (`https://stage-bot.<домен>`, на проде `https://bot.<домен>`) — kamal-proxy не отдаёт один
    хост с TLS двум ролям. Пусто — APP_API_PUBLIC_URL (bot и web за одним адресом)."""
    webhook_secret: SecretStr | None = None
    """secret_token webhook: Telegram присылает его в X-Telegram-Bot-Api-Secret-Token, без него
    или с чужим — 401. 32–256 символов [A-Za-z0-9_-], на stage и проде — `make gen-secret`."""
    mini_app_url: str | None = None
    use_test_environment: bool = False
    support_username: str | None = None
    """Аккаунт поддержки для /help (K23, Q25), без `@`; пусто — «контакт появится скоро»."""
    moderators_chat_id: int | None = None
    """Закрытый чат модераторов (K29, 2.5b): туда бот присылает карточки кейсов и алерт падения
    response rate@4h (6.6). Id группы — отрицательный (`-100…`); пусто — карточек нет, кейсы решают
    командами `cli`, алерт уходит в лог и Sentry."""
    fake_sender: bool = False
    """Нагрузочный прогон на stage (8.3): уведомления не уходят в Telegram, а ждут слот того же
    лимитера и латентность Bot API (platform/telegram/fake_sender.py). На проде запрещён."""

    @field_validator("moderators_chat_id", mode="before")
    @classmethod
    def _moderators_chat_id(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("support_username")
    @classmethod
    def _support_username(cls, value: str | None) -> str | None:
        username = (value or "").strip().removeprefix("@")
        if not username:
            return None
        if not _TELEGRAM_USERNAME.fullmatch(username):
            raise ValueError("TELEGRAM_SUPPORT_USERNAME: 5–32 символа [A-Za-z0-9_], без @")
        return username


def admin_base_url(app: AppSettings) -> str | None:
    """Адрес админки без `/` в конце: APP_ADMIN_PUBLIC_URL, в dev и тестах без него —
    APP_API_PUBLIC_URL + /admin. На stage и проде без него — None: `/admin` на хосте API закрыт
    (WAF), админка — только на своём хосте за Access, ссылки в неё нет."""
    if app.admin_public_url:
        return app.admin_public_url.rstrip("/")
    if app.env in {Environment.STAGE, Environment.PRODUCTION}:
        return None
    return f"{app.api_public_url.rstrip('/')}/admin"


def webhook_base_url(app: AppSettings, telegram: TelegramSettings) -> str:
    """Адрес процесса bot для Telegram: TELEGRAM_WEBHOOK_BASE_URL, без него — APP_API_PUBLIC_URL."""
    return telegram.webhook_base_url or app.api_public_url


def webhook_problems(app: AppSettings, telegram: TelegramSettings) -> list[str]:
    """Чего не хватает режиму webhook; пусто — всё есть или бот на polling.

    Общая проверка процессов (Settings) и `cli bot-setup`: без секрета aiogram принял бы любой
    POST, а на http:// Telegram апдейты не шлёт. Формат секрета и адреса проверяем только здесь:
    в dev на polling они не нужны и не должны ронять стенд."""
    if telegram.updates is not UpdatesMode.WEBHOOK:
        return []
    found = []
    secret = telegram.webhook_secret.get_secret_value() if telegram.webhook_secret else ""
    if not secret:
        found.append("не задан TELEGRAM_WEBHOOK_SECRET")
    elif not _WEBHOOK_SECRET.fullmatch(secret):
        found.append("TELEGRAM_WEBHOOK_SECRET: нужно 32–256 символов [A-Za-z0-9_-]")
    name = "TELEGRAM_WEBHOOK_BASE_URL" if telegram.webhook_base_url else "APP_API_PUBLIC_URL"
    base = urlsplit(webhook_base_url(app, telegram))
    if base.scheme != "https" or not base.hostname:
        found.append(f"{name}: webhook Telegram принимает только https://")
    elif base.path.strip("/") or base.query or base.fragment:
        # kamal-proxy ведёт на bot весь хост: с путём апдейты ушли бы мимо обработчика (404)
        found.append(f"{name}: нужны только схема и хост, без пути")
    return found


class JwtSettings(_Group):
    model_config = SettingsConfigDict(env_prefix="JWT_")

    issuer: str = "sosed"
    access_ttl_seconds: int = Field(default=900, ge=60)
    refresh_ttl_days: int = Field(default=30, ge=1)
    """Мобильные приложения; Mini App — refresh_ttl_days_tma (ADR-0009)."""
    refresh_ttl_days_tma: int = Field(default=7, ge=1)
    keys: SecretStr | None = None
    """`kid:ключ,kid:ключ` (Ed25519, base64url); первый подписывает. Создаёт `cli jwt-keys`."""


class S3Settings(_Group):
    model_config = SettingsConfigDict(env_prefix="S3_")

    endpoint_url: str | None = None
    region: str = "auto"
    access_key_id: SecretStr | None = None
    secret_access_key: SecretStr | None = None
    bucket_incoming: str = "incoming"
    bucket_media: str = "media"
    bucket_private: str = "private"
    public_base_url: str | None = None
    public_endpoint_url: str | None = None
    """Адрес S3, доступный телефону: им подписываются presigned-ссылки (dev — туннель Garage)."""


class SentrySettings(_Group):
    model_config = SettingsConfigDict(env_prefix="SENTRY_")

    dsn: SecretStr | None = None
    traces_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)


class MetricsSettings(_Group):
    """Экспорт метрик Prometheus (DEVELOPMENT_PLAN 3.3): отдельный порт процесса, а не API.

    kamal-proxy ведёт только на порт web (APP_WEB_PORT), поэтому этот порт виден лишь в сети
    Docker — его читает Grafana Alloy. Без порта метрики живут в процессе (dev, тесты)."""

    model_config = SettingsConfigDict(env_prefix="METRICS_")

    port: int | None = Field(default=None, ge=1, le=65535)
    host: str = "127.0.0.1"
    """Локально — только loopback; в контейнере — 0.0.0.0 (порт не публикуется наружу)."""


class HealthchecksSettings(_Group):
    """Healthchecks.io (K33): «пульс» воркера раз в минуту, задача `ops.heartbeat`."""

    model_config = SettingsConfigDict(env_prefix="HEALTHCHECKS_", populate_by_name=True)

    worker_ping_url: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("HEALTHCHECKS_WORKER_PING_URL", "APP_HEARTBEAT_URL"),
    )
    """Ping URL проверки воркера; без адреса — только запись в лог. Секрет: по ссылке любой
    отметит проверку и скроет сбой. APP_HEARTBEAT_URL — прежнее имя (до 3.3)."""


class AiSettings(_Group):
    """AI-проверки контента (ADR-0016 §3). Без ключа — заглушки (platform/ai/stubs.py): в dev
    и тестах конвейер работает на них, на stage/prod без ключей тексты проверяют только
    стоп-правила, а каждое фото решает модератор (K25, K26 — после MVP, решение владельца
    2026-10-05)."""

    model_config = SettingsConfigDict(env_prefix="AI_")

    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    moderation_model: str = "omni-moderation-latest"
    classifier_model: str = "claude-haiku-4-5"
    """ADR-0016: Claude Haiku 4.5 — дёшево и быстро для меток; смена модели — решение владельца."""
    timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    """Проверка стоит на пути публикации: дольше — вердикт «недоступно», решит человек."""


class AnalyticsSettings(_Group):
    model_config = SettingsConfigDict(env_prefix="ANALYTICS_")

    posthog_api_key: SecretStr | None = None
    posthog_host: str = "https://eu.i.posthog.com"
    posthog_personal_api_key: SecretStr | None = None
    """Personal API key PostHog (K32a). На Маке владельца — scope dashboard и insight на чтение
    и запись для `cli posthog-dashboard`. На stage и prod — отдельный ключ только со scope
    `person:write`: воркер удаляет персону по UserDeleted (2.12b); без него при включённом
    PostHog удаление — no-op с предупреждением, а prod с ключом проекта без него не стартует.
    Ключ проекта (`phc_…`) только принимает события, personal key открывает данные — в чат его
    не присылают."""
    posthog_project_id: int | None = Field(default=None, ge=1)
    """Id проекта PostHog (Project settings → Project ID): `cli posthog-dashboard` и удаление
    персоны по UserDeleted."""
    beta_start: date = date(2027, 1, 25)
    """Понедельник первой недели закрытой беты (ориентир плана 6.7): `cli beta-report --week 1`
    — неделя с этого дня, `--week 0` — неделя перед стартом."""
    response_rate_alert_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    """Алерт 6.6: response rate@4h за 7 дней ниже порога. 0,70 — цель MVP из PRODUCT (R06)."""
    response_rate_alert_min_jobs: int = Field(default=10, ge=1)
    """Меньше заявок с созревшим окном — алерт молчит: на трёх заявках доля ничего не значит."""

    def deletion_gaps(self) -> list[str]:
        """События уходят в PostHog, а для удаления персоны (K32a) нет ключа или id проекта:
        имена недостающих переменных; PostHog выключен или всё задано — пусто."""
        if self.posthog_api_key is None:
            return []
        missing = {
            "ANALYTICS_POSTHOG_PERSONAL_API_KEY": self.posthog_personal_api_key,
            "ANALYTICS_POSTHOG_PROJECT_ID": self.posthog_project_id,
        }
        return [name for name, value in missing.items() if value is None]

    @field_validator("posthog_host")
    @classmethod
    def _https_host(cls, value: str) -> str:
        # http:// PostHog отвечает редиректом, и события терялись бы без ошибки
        if not value.startswith("https://"):
            raise ValueError("ANALYTICS_POSTHOG_HOST: нужен https:// адрес")
        return value.rstrip("/")


TODO_PREFIX = "[TODO"
"""Значение-заглушка: владелец ещё не решил. На проде процесс с заглушкой не стартует."""


class LegalSettings(_Group):
    """Подстановки правовых документов (DEVELOPMENT_PLAN 1.5a): `{{OPERATOR_NAME}}`,
    `{{CONTACT_EMAIL}}` в backend/content/legal. Заглушки видны в тексте на dev и stage."""

    model_config = SettingsConfigDict(env_prefix="LEGAL_")

    operator_name: str = "[TODO K22: оператор данных — решает владелец, ADR-0018]"
    contact_email: str = "[TODO K22: почта поддержки — решает владелец, K23]"

    def todo_fields(self) -> list[str]:
        """Поля, где осталась заглушка [TODO …]: переменные окружения для сообщения об ошибке."""
        prefix = str(self.model_config.get("env_prefix", ""))
        return [
            prefix + name.upper()
            for name in type(self).model_fields
            if str(getattr(self, name)).startswith(TODO_PREFIX)
        ]


GROUPS: tuple[type[_Group], ...] = (
    AppSettings,
    DbSettings,
    ValkeySettings,
    TelegramSettings,
    JwtSettings,
    S3Settings,
    SentrySettings,
    MetricsSettings,
    HealthchecksSettings,
    AiSettings,
    AnalyticsSettings,
    LegalSettings,
)


class Settings:
    """Все группы настроек процесса. Создаётся один раз в entrypoint и кладётся в DI."""

    def __init__(self, env_file: Path | None = ENV_FILE) -> None:
        if os.environ.get("APP_ENV") == "":
            # пустое значение в окружении превратилось бы в dev (env_ignore_empty) — и в заглушки
            # AI, которые пропускают всё; в backend/.env пустой APP_ENV — это dev и остаётся
            raise SettingsError("APP_ENV задан пустым: укажите dev, test, stage или production")
        values: dict[type[_Group], _Group] = {}
        missing: list[str] = []
        invalid: list[str] = []
        for group in GROUPS:
            try:
                values[group] = group(_env_file=env_file)  # type: ignore[call-arg]  # параметр pydantic-settings
            except ValidationError as exc:
                prefix = str(group.model_config.get("env_prefix", ""))
                for error in exc.errors():
                    name = prefix + str(error["loc"][0]).upper()
                    (missing if error["type"] == "missing" else invalid).append(name)
        if missing or invalid:
            parts = []
            if missing:
                parts.append("не заданы: " + ", ".join(missing))
            if invalid:
                parts.append("неверные значения: " + ", ".join(invalid))
            raise SettingsError("Настройки неполны — " + "; ".join(parts))
        self.app = _as(values, AppSettings)
        self.db = _as(values, DbSettings)
        self.valkey = _as(values, ValkeySettings)
        self.telegram = _as(values, TelegramSettings)
        self.jwt = _as(values, JwtSettings)
        self.s3 = _as(values, S3Settings)
        self.sentry = _as(values, SentrySettings)
        self.metrics = _as(values, MetricsSettings)
        self.healthchecks = _as(values, HealthchecksSettings)
        self.ai = _as(values, AiSettings)
        self.analytics = _as(values, AnalyticsSettings)
        self.legal = _as(values, LegalSettings)
        if (
            self.app.env in (Environment.STAGE, Environment.PRODUCTION)
            and self.app.hash_key is None
        ):
            raise SettingsError("Настройки неполны — не заданы: APP_HASH_KEY")
        if (
            self.app.env in (Environment.STAGE, Environment.PRODUCTION)
            and self.app.admin_session_key is not None
            and self.app.totp_key is None
        ):
            # админка включена, а секреты TOTP персонала зашифровать нечем: ключ разработки на
            # stage и проде — не ключ (8.4)
            raise SettingsError(
                "Настройки неполны — не заданы: APP_TOTP_KEY (админка включена: есть"
                " APP_ADMIN_SESSION_KEY)"
            )
        if problems := webhook_problems(self.app, self.telegram):
            raise SettingsError("TELEGRAM_UPDATES=webhook — " + "; ".join(problems))
        if self.app.env is Environment.PRODUCTION and (todo := self.legal.todo_fields()):
            # оператор и почта попадают в политику конфиденциальности: заглушка на проде — нарушение
            raise SettingsError("Настройки неполны — на проде нужны значения: " + ", ".join(todo))
        if self.app.env is Environment.PRODUCTION and self.telegram.fake_sender:
            # фейк молча глотает уведомления: на проде люди перестали бы их получать
            raise SettingsError(
                "Неверные настройки — TELEGRAM_FAKE_SENDER только для нагрузочного прогона на stage"
            )
        if self.app.env is Environment.PRODUCTION and (gaps := self.analytics.deletion_gaps()):
            # события уходят в PostHog, а удалить персону по UserDeleted нечем (2.12b, K32a):
            # удаление аккаунта молча не доходило бы до PostHog. На stage — предупреждение (di.py)
            raise SettingsError(
                "Настройки неполны — при ANALYTICS_POSTHOG_API_KEY на проде нужны: "
                + ", ".join(gaps)
            )


def _as[T: _Group](values: dict[type[_Group], _Group], group: type[T]) -> T:
    value = values[group]
    assert isinstance(value, group)  # noqa: S101 — инвариант сборки выше
    return value


def env_names(group: type[_Group]) -> list[str]:
    """Имена переменных окружения группы — для .env.example и проверок."""
    prefix = str(group.model_config.get("env_prefix", ""))
    return [prefix + name.upper() for name in group.model_fields]


def describe(settings: Settings) -> dict[str, Any]:
    """Сводка настроек без секретов — для логов старта.

    Флаги внешних сервисов (sentry, heartbeat, ai_*, posthog) — то, по чему на воротах 3.4 и 8.4
    сверяют политику конфиденциальности с включёнными обработчиками (ARCHITECTURE §13.6)."""
    return {
        "env": settings.app.env.value,
        "release": settings.app.release,
        "db_pool_size": settings.db.pool_size,
        "telegram_bot": settings.telegram.bot_username,
        "telegram_updates": settings.telegram.updates.value,
        "telegram_fake_sender": settings.telegram.fake_sender,
        "s3_endpoint": settings.s3.endpoint_url,
        "sentry": settings.sentry.dsn is not None,
        "metrics_port": settings.metrics.port,
        "heartbeat": settings.healthchecks.worker_ping_url is not None,
        "ai_moderation": settings.ai.openai_api_key is not None,
        "ai_classifier": settings.ai.anthropic_api_key is not None,
        "posthog": settings.analytics.posthog_api_key is not None,
    }
