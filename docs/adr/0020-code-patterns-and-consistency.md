# ADR-0020: Паттерны кода и единообразие — слои модуля, Unit of Work, Repository, синглтоны через DI

- **Статус:** принято
- **Дата:** 2026-09-27
- **Уточняет:** [ADR-0002](0002-modular-monolith.md) (п. 3: линтер границ — import-linter), [ADR-0004](0004-backend-stack-fastapi-sqlalchemy.md) (mypy strict на весь `src/app`), [ADR-0008](0008-background-jobs-and-outbox.md) (п. 3: кто регистрирует события; п. 6: `queueing_lock` внутри транзакции приложения), ARCHITECTURE.md §5.5 и §6 (единый шаблон модуля, `di.py`, `errors.py`, `platform/kernel`, `platform/http`). Полный список — [§16](#16-что-уточняется-в-других-документах).
- **Связанные документы:** [DEVELOPMENT_PLAN.md](../DEVELOPMENT_PLAN.md) (шаги, в которых вводится каркас, — раздел «Что сделать»), [ARCHITECTURE.md §5](../ARCHITECTURE.md#5-модульная-структура-backend), [§6](../ARCHITECTURE.md#6-структура-репозитория), [§8.3](../ARCHITECTURE.md#83-формат-ошибок-rfc-9457-problem-details), [§12.1](../ARCHITECTURE.md#121-события-и-задачи), [§13.2](../ARCHITECTURE.md#132-аутентификация-и-авторизация), [ADR-0003](0003-api-first-rest-openapi.md), [ADR-0012](0012-mini-app-frontend-and-mobile-path.md), [ADR-0013](0013-i18n-multilingual-content.md), [research/03 §3.4](../research/03-backend-stack.md#34-repository-и-unit-of-work--прагматично), [§9.8–9.9](../research/03-backend-stack.md#98-di)

## Контекст

- **Кто пишет код.** Код пишет ИИ-ассистент маленькими шагами, владелец продукта проверяет каждый шаг. Проверять можно, только если все модули устроены одинаково: кто прочитал один модуль, тот прочитает любой.
- **Что уже решено.** Модульный монолит с фасадами и DAG ([ADR-0002](0002-modular-monolith.md)). Unit of Work поверх `AsyncSession` и постановка задач Procrastinate в той же транзакции ([ADR-0008](0008-background-jobs-and-outbox.md)). dishka как DI и Pydantic только на границах ([ADR-0004](0004-backend-stack-fastapi-sqlalchemy.md)). Ошибки RFC 9457 ([ADR-0003](0003-api-first-rest-openapi.md)). Фронтенд-монорепо с `packages/*` ([ADR-0012](0012-mini-app-frontend-and-mobile-path.md)).
- **Что не решено или решено по-разному:**
  - ARCHITECTURE §5.5 требует «domain — чистый Python без I/O», а research/03 §3.4 предлагает ORM-модели как сущности в большинстве модулей и чистый домен только для заявок, откликов и рейтинга. В одном коде получились бы два стиля.
  - Не записано, где в слоях стоит `infrastructure` и может ли `application` её импортировать.
  - Синглтоны нигде не описаны. Без правила появятся глобальные клиенты на уровне модулей.
  - Фасад нижнего модуля должен работать в транзакции вызывающего (принятие отклика создаёт сделку атомарно), но как это совместить с запретом вложенных транзакций, не сказано.
  - «Тонкий» вариант для `geo` и `catalog` (§5.5) даёт второй шаблон модуля.
- **Решение владельца (2026-09-27):** используем самые проверенные паттерны — Unit of Work, Repository, Singleton по необходимости и другие — и придерживаемся одного стиля во всём коде приложения.

## Рассмотренные варианты

| Вариант | Плюсы | Минусы |
|---|---|---|
| **A. Прагматичный микс** (research/03 §3.4): ORM-модели служат сущностями, чистый домен и репозитории есть только в «богатых» модулях | Меньше кода на старте | Два стиля в одном коде. ORM и ленивые загрузки протекают в use cases. Вопрос «какой стиль здесь» решается заново в каждом модуле |
| **B. Порты и адаптеры + Data Mapper во всех модулях**: domain на dataclass, ORM только в `infrastructure`, репозитории и query-сервисы за `Protocol`, UoW с событиями, зависимости через dishka | Один шаблон на все модули. Domain тестируется без БД. ORM не выходит за `infrastructure`. Границы проверяет линтер. Замена инфраструктуры не трогает use cases | Больше кода: маппинг ORM ↔ domain и `Protocol` на каждый порт |
| **C. Как B, но с императивным маппингом SQLAlchemy** (`registry.map_imperatively`) прямо на доменные dataclass | Нет второго класса на сущность, изменения отслеживает сессия | Доменные объекты в рантайме инструментированы ORM: expire и `lazy="raise"` срабатывают внутри доменных методов. Нельзя `frozen` и `slots`. Поведение сложнее объяснить в ревью |
| **D. «Полный» DDD/CQRS**: шина команд, отдельные read-БД, event sourcing | Максимальная развязка | Избыточно для 1–2 человек и сотен RPS. ADR-0002 и ADR-0008 уже выбрали одну БД и очередь в PostgreSQL |

Выбран **B**: цену (маппинг и протоколы) снижают шаблон модуля и генератор (§12), а выигрыш в единообразии растёт с каждым модулем. Чтобы B не разросся, фейков БД не пишем: use cases тестируются на настоящем PostgreSQL (§11), а записи без бизнес-правил обходятся без доменного агрегата (§5).

## Решение

### 1. Слои модуля и правило зависимостей

Все 15 доменных модулей в `modules/` устроены по одному шаблону, включая `billing` (пустой каркас до v1). Обязательны `api.py`, `errors.py`, `di.py`, `domain/`, `application/`, `infrastructure/` и `tests/`: пустой слой — пакет с одним `__init__.py`. Входные адаптеры (`http/`, `bot/`, `admin/`, `tasks.py`) создаются, только когда нужны.

```text
modules/jobs/
├── api.py                  # контракт для других модулей: Protocol JobsApi, DTO, реэкспорт публичных ошибок
├── errors.py               # все ошибки модуля с code (нижний слой: их видят domain, api и адаптеры)
├── di.py                   # dishka Provider модуля: связывает порты с реализациями, строит JobsConfig
├── domain/                 # чистый Python: агрегаты, value objects, state machine, политики
│   ├── job.py              #   агрегат Job, JobStatus, переходы
│   ├── response.py         #   подагрегат «отклик» — файлом внутри слоя, не отдельным пакетом
│   └── policies.py
├── application/
│   ├── ports.py            # Protocol: JobRepository, JobFeedQuery, внешние сервисы; TaskRef задач модуля
│   ├── dto.py              # результаты, read-DTO, payload задач (frozen dataclass)
│   ├── config.py           # JobsConfig: параметры модуля (frozen dataclass), если они есть
│   ├── facade.py           # JobsFacade — реализация JobsApi
│   └── use_cases/
│       ├── close_job.py    #   CloseJobCommand + CloseJob
│       └── accept_response.py
├── infrastructure/
│   ├── models.py           # ORM: JobRow, ResponseRow (MetaData(schema="jobs"))
│   ├── mappers.py          # JobRow ⇄ Job
│   ├── repositories.py     # SqlJobRepository
│   └── queries.py          # SqlJobFeedQuery
├── http/                   # по необходимости
│   ├── router.py           # APIRouter с тонкими хендлерами
│   └── schemas.py          # Pydantic: ...In / ...Out
├── bot/handlers.py         # по необходимости: aiogram Router
├── admin/views.py          # по необходимости: SQLAdmin ModelView
├── tasks.py                # по необходимости: Procrastinate Blueprint и подписки на события
└── tests/{unit,integration,api}/
```

Слои сверху вниз. Импортировать можно только вниз:

| Слой | Роль | Может импортировать | Не может |
|---|---|---|---|
| `di.py` | Сборка модуля | Всё своего модуля, группы настроек `platform/settings.py` | — |
| `http`, `bot`, `admin`, `tasks` | Входные адаптеры | `application`, перечисления из `domain`, `errors`, `platform`, фреймворки | `infrastructure` (кроме `admin/views` → `infrastructure/models`, см. ниже), друг друга |
| `infrastructure` | Выходные адаптеры | `application` (порты, DTO), `domain`, `errors`, адаптеры `platform`, SQLAlchemy и клиенты сервисов | Входные адаптеры, внутренности чужих модулей |
| `application` | Use cases, фасад, порты | `domain`, `api` и `errors` своего модуля, `api` нижних модулей по DAG, `platform/kernel`, `platform/contracts`, порты `platform/*/port.py`, `structlog` | `infrastructure`, фреймворки, драйверы и SDK (полный список — контракт `pure-core` ниже) |
| `domain`, `api` | Модель и контракт | stdlib, `errors` своего модуля, `platform/kernel`, `platform/contracts` | Всё остальное; `domain` и `api` не импортируют друг друга |
| `errors` | Ошибки модуля | stdlib, `platform/kernel` (базовые классы ошибок) | Всё остальное |

- **Зависимости направлены внутрь.** Входные и выходные адаптеры зависят от `application`, та — от `domain`. Всё внешнее `application` получает через порты (`Protocol`), реализации подставляет DI. Это уточняет схему research/03 §9.9 (`api | bot | worker → application → domain`): `infrastructure` стоит рядом с входными адаптерами, а не под `application`.
- **Ошибки — в `errors.py` модуля.** Их бросают `domain` (`JobNotOpenError`) и `infrastructure` (`JobNotFoundError`), а ловят другие модули. Поэтому `errors.py` лежит ниже `domain` и `api`. `api.py` реэкспортирует публичные ошибки (`from app.modules.jobs.errors import JobNotFoundError as JobNotFoundError`), другие модули импортируют их только из `api.py`. Второго объявления ошибки и перевода ошибок в фасаде нет.
- **Одно исключение.** SQLAdmin работает только с ORM-классами, поэтому `admin/views.py` импортирует `infrastructure/models.py`. Правка через SQLAdmin разрешена только для справочников (`geo`, `catalog`, `platform.client_config`, feature flags). SQLAdmin сам коммитит свою сессию, событие после правки публикуется отдельной транзакцией (§4). Действия над агрегатами с инвариантами (решение модерации, санкция) идут через use case.
- **Порты платформы** лежат в `platform/<пакет>/port.py` (`platform/db/port.py` — `UnitOfWork`, `platform/queue/port.py` — `JobQueue` и `TaskRef`, `platform/audit/port.py` — `AuditLog`, `platform/storage/port.py`, `platform/ai/port.py`, `platform/telegram/port.py`). Адаптеры лежат в соседних файлах, `__init__.py` подпакетов пустые. Иначе импорт порта потянет за собой драйвер, и линтер это поймает.
- **Чистые типы платформы** — в подпакете `platform/kernel`: `AggregateRoot`, `VersionedAggregate`, `StatusChange`, `Money`, `LocalizedText`, `GeoPoint`, типизированные ID, `Principal`, `Page`/`PageRequest`, `Clock`, базовые ошибки.

Контракты в `backend/.importlinter`. import-linter читает INI без встроенных комментариев, поэтому комментарий — только отдельной строкой. Маски `*` в `containers`, `source_modules` и `ignore_imports` и необязательные слои в скобках есть в документации import-linter; шаг `import-linter-dag` (шаг [0.2](../DEVELOPMENT_PLAN.md#02-скелет-backend-и-границы-модулей) плана) подтверждает их негативным тестом.

```ini
[importlinter]
root_package = app
include_external_packages = True

[importlinter:contract:module-layers]
name = Слои внутри модуля (ADR-0020 §1)
type = layers
containers =
    app.modules.*
layers =
    di
    (http) | (bot) | (admin) | (tasks) | infrastructure
    application
    domain | api
    errors
ignore_imports =
    # SQLAdmin, только справочники (ADR-0020 §1)
    app.modules.*.admin.views -> app.modules.*.infrastructure.models

[importlinter:contract:pure-core]
name = domain, application и контракты без фреймворков (ADR-0020 §1)
type = forbidden
source_modules =
    app.modules.*.domain
    app.modules.*.application
    app.modules.*.api
    app.modules.*.errors
    app.platform.kernel
    app.platform.contracts
    app.platform.*.port
forbidden_modules =
    sqlalchemy
    geoalchemy2
    psycopg
    fastapi
    starlette
    sqladmin
    aiogram
    aiohttp
    procrastinate
    redis
    valkey
    boto3
    botocore
    aiobotocore
    httpx
    openai
    anthropic
    jwt
    sentry_sdk
    pydantic
    pydantic_settings
    dishka
```

- Контракты DAG между модулями и «снаружи виден только `api`» остаются как в [ADR-0002](0002-modular-monolith.md). Контракт «только `api`» проверяет прямые импорты (`allow_indirect_imports = True` или тип `protected`): `api.py` законно импортирует `errors.py` своего модуля.
- `forbidden` проверяет и транзитивные импорты: если `application` через цепочку дотянется до `sqlalchemy`, проверка упадёт. Пакеты из списка, которых нет в графе импортов, import-linter пропускает, так что список можно держать с запасом.
- Список запретов неизбежно отстаёт от зависимостей, поэтому основную защиту даёт разрешающий архитектурный тест (§15): в `domain`, `api`, `errors`, `platform/kernel`, `platform/contracts` и портах платформы сторонних импортов нет, только stdlib; в `application` из сторонних разрешён только `structlog`.

### 2. Domain: агрегаты, value objects, state machine, политики

- **Агрегат** — dataclass с идентификатором, инвариантами и методами-переходами (`job.close(...)`, `deal.confirm(...)`). Наследует `AggregateRoot` из `platform/kernel`, а если его правят двое — `VersionedAggregate` (поле `version`). Состояние меняется только методами агрегата, снаружи поля не присваиваются. Границы агрегатов (например, входят ли отклики в агрегат заявки) определяет шаг конкретного модуля. Один корень агрегата — один репозиторий. Записи без бизнес-правил агрегатом не оформляются (§5, «простая запись»).
- **Value object** — `@dataclass(frozen=True, slots=True)` с проверкой в `__post_init__`. Общие VO — в `platform/kernel`.
- **State machine** у каждого агрегата со статусом устроена одинаково: `StrEnum` статусов, таблица разрешённых переходов `_ALLOWED` и один метод `_move_to(target, *, error, by, now, reason=None)`. Таблица — единственный источник правды о допустимости перехода. Метод-переход передаёт в `_move_to` свою ошибку конфликта, поэтому у каждого перехода стабильный смысловой `code` (`job_not_open` у закрытия и отклика, `job_not_draft` у публикации).
- **История переходов** (`*.status_history`). `_move_to` добавляет в агрегат запись `StatusChange(from_, to, actor_id, reason, at)`, репозиторий в `save` забирает их (`pull_history()`) и вставляет строки. Сам репозиторий статусы не сравнивает.
- **Политики** — функции в `domain/policies.py`: владение ресурсом, «может ли исполнитель откликнуться». Роутер права не проверяет ([§13.2](../ARCHITECTURE.md#132-аутентификация-и-авторизация)).
- **Время и ID.** Domain не вызывает `datetime.now()`: текущее время приходит параметром `now` из порта `Clock`. Новые идентификаторы — `new_id()` из `platform/kernel` (UUIDv7).
- **События** — frozen dataclass из `platform/contracts/events/<модуль>.py`. Агрегат создаёт их в методе-переходе через `self._record(...)`.
- **Domain синхронный.** В нём нет I/O, поэтому нет и `async`, логирования и Pydantic.

```python
# platform/kernel/aggregate.py
@dataclass(eq=False, kw_only=True)
class AggregateRoot:
    _events: list[DomainEvent] = field(default_factory=list, init=False, repr=False)

    def _record(self, event: DomainEvent) -> None:
        self._events.append(event)

    def pull_events(self) -> list[DomainEvent]:            # вызывает только UoW при commit
        events, self._events = self._events, []
        return events


@dataclass(eq=False, kw_only=True)
class VersionedAggregate(AggregateRoot):
    version: int

    def ensure_version(self, expected: int | None) -> None:
        if expected is not None and expected != self.version:
            raise StaleVersionError(expected=expected, actual=self.version)   # 412

    def mark_persisted(self, *, version: int) -> None:     # вызывает только репозиторий после flush
        self.version = version


def aggregate_state(aggregate: AggregateRoot) -> dict[str, object]:
    """Снимок публичного состояния (поля без «_»): по нему UoW ловит забытый save, а тесты сравнивают агрегаты."""
    return {f.name: deepcopy(getattr(aggregate, f.name))
            for f in fields(aggregate) if not f.name.startswith("_")}
```

```python
# modules/jobs/domain/job.py
class JobStatus(StrEnum):
    DRAFT = "draft"
    PENDING_MODERATION = "pending_moderation"
    PUBLISHED = "published"
    ASSIGNED = "assigned"
    CLOSED = "closed"
    # …

_ALLOWED: Final[Mapping[JobStatus, frozenset[JobStatus]]] = {
    JobStatus.PUBLISHED: frozenset({JobStatus.ASSIGNED, JobStatus.CLOSED, JobStatus.EXPIRED}),
    # … полная таблица — ARCHITECTURE §7.9
}


@dataclass(eq=False, kw_only=True)
class Job(VersionedAggregate):
    id: JobId
    owner_id: UserId
    status: JobStatus
    _history: list[StatusChange[JobStatus]] = field(default_factory=list, init=False, repr=False)

    def close(self, *, actor_id: UserId, reason: CloseReason, now: datetime) -> None:
        ensure_owner(self.owner_id, actor_id)                                 # ForbiddenError → 403
        self._move_to(JobStatus.CLOSED, error=JobNotOpenError, by=actor_id, now=now, reason=reason)
        self._record(JobClosed(job_id=self.id, reason=reason, occurred_at=now))

    def pull_history(self) -> list[StatusChange[JobStatus]]:                 # вызывает репозиторий в save
        history, self._history = self._history, []
        return history

    def _move_to(self, target: JobStatus, *, error: type[ConflictError], by: UserId | None,
                 now: datetime, reason: str | None = None) -> None:
        if target not in _ALLOWED.get(self.status, frozenset()):
            raise error(job_id=self.id, status=self.status, target=target)   # 409, code — у класса ошибки
        self._history.append(StatusChange(from_=self.status, to=target, actor_id=by,
                                          reason=reason, at=now))
        self.status = target
```

Агрегат — сущность: `eq=False`, сравнение по идентичности объекта. Состояние двух экземпляров сравнивает `aggregate_state`, в тестах — хелпер `assert_same_state(a, b)` из `platform/testing`.

**Тонкие модули** (`geo`, `catalog`) используют тот же шаблон. Их `domain/` содержит только перечисления и value objects, агрегатов и репозиториев нет. Чтение идёт через query-сервисы, записи из прикладного кода нет: справочники правятся в админке и сидами. У `search` в `domain/` лежит формула ранжирования (чистые функции), а индекс обновляет проектор (§5).

### 3. Application: use cases, фасад, порты

- **Use case** — один класс на одно действие пользователя или системы. Файл `application/use_cases/<глагол>_<объект>.py`, метод `async def __call__(self, cmd)`. Use case открывает транзакцию, загружает агрегаты через репозитории, вызывает методы domain и сохраняет результат. Вызывают его только входные адаптеры своего модуля: роутер, хендлер бота, задача, админка.
- **Команда** — frozen dataclass `<UseCase>Command` в файле своего use case, рядом с классом. В `application/dto.py` лежат результаты (`JobRef`), read-DTO query-сервисов и payload задач. Pydantic в application не используется ([ADR-0004](0004-backend-stack-fastapi-sqlalchemy.md)).
- **Порты** — `Protocol` в `application/ports.py`: репозитории, query-сервисы, внешние сервисы модуля. Там же константы `TaskRef` задач модуля.
- **Параметры модуля** (лимит откликов, TTL) приходят frozen dataclass `<Модуль>Config` из `application/config.py`. Его строит `di.py` из группы настроек. Pydantic-настройки видят только `platform`, `di.py` и адаптеры.
- **Ограничения** из `identity.restrictions` проверяет use case через фасад `identity`; при запрете — `RestrictedError` (403 `restricted`).
- **Внешняя запись** (отправка в Telegram, удаление из S3, вызов AI) в use case не выполняется. Use case ставит задачу через порт `JobQueue`, и она выполнится после commit.
- **Внешнее чтение** (HEAD-проверка загрузки в S3 перед переходом `media` в `uploaded`) выполняется до `async with uow`: внутри блока соединение с БД не ждёт сети.
- Правила живут в domain, поэтому use case короткий: 10–30 строк оркестровки.

```python
# modules/jobs/application/use_cases/close_job.py
@dataclass(frozen=True, slots=True, kw_only=True)
class CloseJobCommand:
    actor_id: UserId
    job_id: JobId
    reason: CloseReason
    expected_version: int | None        # из If-Match


class CloseJob:
    def __init__(self, uow: UnitOfWork, jobs: JobRepository,
                 identity: IdentityApi, clock: Clock) -> None:
        self._uow, self._jobs, self._identity, self._clock = uow, jobs, identity, clock

    async def __call__(self, cmd: CloseJobCommand) -> JobRef:
        await self._identity.ensure_allowed(cmd.actor_id, Action.POST_JOBS)   # чтение, до транзакции
        async with self._uow:                                   # граница транзакции
            job = await self._jobs.get(cmd.job_id)
            job.ensure_version(cmd.expected_version)            # StaleVersionError → 412
            job.close(actor_id=cmd.actor_id, reason=cmd.reason, now=self._clock.now())
            await self._jobs.save(job)                          # flush: version уже новая
        return JobRef(id=job.id, version=job.version)
```

**Задачи.** Use case ссылается на задачу типизированной константой, а не строкой и не функцией из `tasks.py`. Payload — frozen dataclass из `application/dto.py`; для подписчиков payload — само событие из `platform/contracts`. Обёртка задач в `platform/queue` валидирует payload через `pydantic.TypeAdapter`, поэтому схема объявлена один раз, отдельных Pydantic-моделей payload нет.

```python
# platform/queue/port.py
@dataclass(frozen=True, slots=True)
class TaskRef[P]:
    name: str                           # "<модуль>.<глагол>_<объект>"
    payload: type[P]


class JobQueue(Protocol):
    async def enqueue[P](self, task: TaskRef[P], payload: P, *, dedup_key: str | None = None) -> None: ...


# modules/media/application/ports.py
DELETE_OBJECT: Final = TaskRef("media.delete_object", DeleteObjectPayload)

# modules/media/tasks.py — входной адаптер
@task(DELETE_OBJECT, queue="default")   # обёртка platform/queue: имя, TypeAdapter, scope dishka, логи
async def delete_object(payload: DeleteObjectPayload, storage: FromDishka[StoragePort]) -> None: ...
```

### 4. Unit of Work

**Граница транзакции**

- **Одна команда — одна транзакция — один `async with uow`.** UoW — тонкая обёртка над `AsyncSession` из REQUEST scope, один экземпляр на HTTP-запрос, Telegram-update или задачу. Последовательные блоки в одном скоупе разрешены (идемпотентность ниже, задача, которая обрабатывает пачку). Свой UoW-фреймворк не пишем ([research/03 §3.4](../research/03-backend-stack.md#34-repository-и-unit-of-work--прагматично)).
- **Сессия.** `async_sessionmaker(expire_on_commit=False)`: после commit атрибуты не истекают, и чтение `job.version` или полей строки в async не даёт `MissingGreenlet`.
- **Вход в блок.** UoW не вызывает `session.begin()` и ведёт собственный флаг `_active`: на нём построены `require_active()` и проверка вложенности. Если транзакцию уже открыло чтение (autobegin SQLAlchemy) и несохранённых изменений нет, UoW её откатывает: терять нечего, соединение начинает блок чистым. Если изменения есть, это запись вне UoW, и UoW бросает `WriteOutsideUnitOfWorkError`.
- **Вложенность запрещена.** Второй `async with uow` при активном блоке бросает `NestedTransactionError`. Savepoint'ы (`begin_nested`) в модулях не используем. Единственное место со savepoint'ом — адаптер очереди в `platform/queue` (ниже).
- **Commit и rollback вызывает только `platform/db`**: UoW и база query-сервисов. `session.commit()` и `session.rollback()` в модулях, роутерах, хендлерах, задачах и фасадах запрещены, это проверяет архитектурный тест (§15).
- **Фасад работает в транзакции вызывающего.** Командный метод фасада вызывает `uow.require_active()` и свою транзакцию не открывает. REQUEST scope выдаёт use case и фасаду один и тот же UoW, поэтому `jobs` атомарно принимает отклик и создаёт сделку через `deals` ([§5.2](../ARCHITECTURE.md#52-правила-модульности) п. 3).
- **Только последовательные вызовы.** `AsyncSession` не допускает конкурентных операций. Внутри одного скоупа dishka фасады, query-сервисы и репозитории вызываются по очереди; `asyncio.gather` и `TaskGroup` над ними запрещены (иначе — плавающий `IllegalStateChangeError` под нагрузкой). Параллельные внешние вызовы без сессии делает адаптер platform (например, пакетная отправка в `platform/telegram`). Если параллельное чтение из БД понадобится по замерам — отдельный read-only провайдер сессий и отдельный ADR.

**Выход из блока**

- **Успешный выход.** UoW проверяет отслеживаемые агрегаты: если состояние агрегата отличается от снимка, сделанного при последнем `get`/`add`/`save`, значит, `save` забыли, и UoW бросает `UnsavedAggregateError`. Затем забирает события у отслеживаемых агрегатов (`pull_events()`) и из `add_event`, диспетчер ставит по задаче Procrastinate на каждого подписчика на том же соединении, и выполняется COMMIT ([ADR-0008](0008-background-jobs-and-outbox.md) п. 3, [§12.1](../ARCHITECTURE.md#121-события-и-задачи)).
- **Исключение в блоке или при commit:** ROLLBACK на обеих ветках, после чего сессия снова пригодна для следующего блока. Данные, события и задачи пропадают вместе, частичной фиксации нет.
- **Конкурентная правка.** `StaleDataError` SQLAlchemy (строку изменил кто-то другой между чтением и записью) превращается в `ConcurrentModificationError` — 409 `concurrent_modification`, в задаче — повтор. Несовпадение `If-Match` проверяет агрегат (`ensure_version`) и бросает `StaleVersionError` — 412.
- **Постановка задач не ломает транзакцию.** Procrastinate с переданным соединением делает INSERT без savepoint, а конфликт `queueing_lock` получает как `UniqueViolation` и превращает в `AlreadyEnqueued`. В PostgreSQL любая ошибка переводит транзакцию в aborted, и вторая правка той же заявки при ожидающем `search.reindex_job` потеряла бы данные пользователя. Поэтому адаптер `JobQueue` ставит каждую задачу внутри `async with raw_conn.transaction()` (psycopg в активной транзакции делает SAVEPOINT), а `AlreadyEnqueued` считает успехом: дубль означает, что задача уже стоит. Пишется в лог на уровне `debug`.

**Чтение**

- **Чтение идёт без UoW.** Query-сервисы и BFF читают через ту же REQUEST-сессию и наследуют `SqlQuery` из `platform/db/query.py`. Вне активного UoW он сразу после запроса завершает транзакцию чтения, и соединение возвращается в пул. Так хендлер бота или задача, которые прочитали данные и ждут Telegram API или rate limiter, не держат соединение «idle in transaction». Внутри блока UoW чтения идут в его транзакции.
- **Отдельного режима «только чтение» у REQUEST-сессии нет.** `statement_timeout` и `idle_in_transaction_session_timeout` (страховка, стартовое значение 30 с) задаются роли `app` в PostgreSQL. Отдельный read-only пул (как `app_goods_read`, [ARCHITECTURE §5.8](../ARCHITECTURE.md#58-модуль-goods-после-mvp-итерация-вещи)) появляется только отдельным решением.
- **До вызова use case входной адаптер в БД не пишет.** Читать можно только через фасад или query-сервис. Например, бот находит `user_id` по `telegram_id` через фасад `identity` с кэшем в Valkey, web собирает `Principal` из клеймов JWT и проверяет denylist `sid` в Valkey. Исключение — идемпотентность (ниже).

**События вне агрегата**

- **Событие без агрегата** регистрируется через `uow.add_event(...)` внутри блока. Других способов нет.
- **Правка справочника в SQLAdmin.** SQLAdmin открывает свою сессию и коммитит сам, до его commit событие в ту же транзакцию не попадёт. Поэтому `after_model_change` и `after_model_delete` справочников вызывают хелпер `platform/http/admin.py::publish_after_admin_commit(request, event)`. Хелпер берёт REQUEST-контейнер запроса (интеграция dishka кладёт его в `request.state`), открывает свой `async with uow` и регистрирует `CatalogChanged` через `uow.add_event`. Если процесс упадёт между commit SQLAdmin и постановкой, событие потеряется; это закрывают идемпотентный реиндекс и ночной `search.reconcile_index`. В коде — комментарий `# ADR-0020: исключение — SQLAdmin коммитит сам`.

**Платформенные записи.** Таблицы `platform.*` пишут только адаптеры platform через свои порты и всегда внутри UoW.

- **Аудит** — порт `AuditLog` (`platform/audit/port.py`). Адаптер требует активный UoW и добавляет строку в сессию текущей транзакции: решение модерации и запись о нём фиксируются вместе. Просмотр ПД персоналом оформляется командой (use case с `async with uow`), чтобы запись в `audit_log` была всегда.
- **Идемпотентность** (`Idempotency-Key` для создающих POST, [ADR-0003](0003-api-first-rest-openapi.md), [ARCHITECTURE §8.1](../ARCHITECTURE.md#81-стиль-и-соглашения)). Зависимость `platform/http/idempotency.py` работает через порт `IdempotencyStore` тремя последовательными блоками в одном скоупе:
  1. До use case — `async with uow` и `reserve()` (`INSERT … ON CONFLICT DO NOTHING` со статусом «в работе»). Если ключ уже есть: готовый ответ возвращается повторно; ключ в работе — 409 `idempotency_in_progress`; другой `request_hash` — 422 `idempotency_key_reused`.
  2. Use case со своим `async with uow`.
  3. После — `async with uow` и `complete()` с кодом и телом ответа. Если use case бросил ошибку, ключ удаляется (`release()`), и повтор выполнится заново.

  Это единственное место, где входной адаптер пишет в БД до use case. Если процесс упал между шагами 2 и 3, ключ остаётся «в работе»: повтор получает 409, дубля нет, ключ удалит `platform.idempotency_cleanup`.
- **Запасной путь ADR-0008** (`platform.outbox` + relay) меняет только адаптер `JobQueue`; relay — задача `platform/queue`, каждая пачка в своём `async with uow`. Use cases остаются прежними.

```python
# platform/db/port.py — порт, его видит application
class UnitOfWork(Protocol):
    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, et: type[BaseException] | None, e: BaseException | None,
                        tb: TracebackType | None) -> None: ...
    def track(self, aggregate: AggregateRoot) -> None: ...   # репозиторий в get, add, save
    def add_event(self, event: DomainEvent) -> None: ...     # событие без агрегата
    def require_active(self) -> None: ...                    # фасад, простая запись, платформенные порты


# platform/db/uow.py — адаптер (сокращённо)
class SqlAlchemyUnitOfWork(UnitOfWork):
    def __init__(self, session: AsyncSession, dispatcher: EventDispatcher) -> None:
        self._session, self._dispatcher = session, dispatcher
        self._active = False
        self._tracked: dict[int, tuple[AggregateRoot, dict[str, object]]] = {}
        self._events: list[DomainEvent] = []

    async def __aenter__(self) -> Self:
        if self._active:
            raise NestedTransactionError
        if self._session.in_transaction():               # транзакцию открыло чтение (autobegin)
            if self._session.new or self._session.dirty or self._session.deleted:
                raise WriteOutsideUnitOfWorkError
            await self._session.rollback()               # были только чтения — ничего не теряем
        self._active = True                              # session.begin() не вызываем
        self._session.info[UOW_ACTIVE] = True
        return self

    def track(self, aggregate: AggregateRoot) -> None:
        self.require_active()                            # репозиторий вне UoW не работает
        self._tracked[id(aggregate)] = (aggregate, aggregate_state(aggregate))

    async def __aexit__(self, et: type[BaseException] | None, e: BaseException | None,
                        tb: TracebackType | None) -> None:
        try:
            if e is not None:
                await self._session.rollback()
                if isinstance(e, StaleDataError):
                    raise ConcurrentModificationError from e    # 409, в задаче — повтор
                return                                          # исходное исключение летит дальше
            try:
                self._ensure_saved()                            # UnsavedAggregateError
                await self._session.flush()
                await self._dispatcher.enqueue(self._pull_events())   # то же соединение
                await self._session.commit()
            except BaseException as err:
                await self._session.rollback()                  # сессия снова пригодна
                if isinstance(err, StaleDataError):
                    raise ConcurrentModificationError from err
                raise
        finally:
            self._reset()                                       # флаг, трекинг, события, session.info


# platform/db/query.py — база query-сервисов (сокращённо)
class SqlQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _fetch(self, stmt: Executable) -> Sequence[RowMapping]:
        rows = (await self._session.execute(stmt)).mappings().all()
        if not self._session.info.get(UOW_ACTIVE):
            await self._session.rollback()               # вне UoW соединение сразу уходит в пул
        return rows


# platform/queue/procrastinate_queue.py — адаптер JobQueue (сокращённо)
class ProcrastinateJobQueue(JobQueue):
    async def enqueue[P](self, task: TaskRef[P], payload: P, *, dedup_key: str | None = None) -> None:
        raw = await self._driver_connection()            # psycopg-соединение текущей транзакции сессии
        try:
            async with raw.transaction():                # в активной транзакции — SAVEPOINT
                await self._defer(raw, task, payload, queueing_lock=dedup_key)
        except AlreadyEnqueued:
            log.debug("task_already_enqueued", task=task.name, dedup_key=dedup_key)
```

### 5. Repository и query-сервисы (CQRS-lite)

**Где что:**

| Операция | Через что |
|---|---|
| Запись в таблицы модуля | Репозиторий (агрегата или простой записи) внутри use case или командного метода фасада |
| Запись в таблицы `platform.*` | Порты platform (`AuditLog`, `IdempotencyStore`), §4 |
| Чтение для экрана своего модуля | Query-сервис |
| Чтение данных другого модуля | Его фасад |
| Составной экран | BFF (`interfaces/http/views`) или read-model `search` |
| Обновление read-model | Проектор из задачи-подписчика |

**Две формы репозитория.** Выбор по одному вопросу: есть ли правило, которое может нарушиться при записи (статус, лимит, владение, согласованность нескольких строк)?

1. **Агрегат** — правило есть. Доменный dataclass, маппер, методы `get`/`get_for_update`/`add`/`save`, версия, события из агрегата. Всё остальное в этом разделе относится к этой форме.
2. **Простая запись** — правила нет: скрытые заявки, настройки уведомлений, избранное, атрибуция рефералов. Репозиторий с командными методами (`hide(user_id, job_id)`, `set_preference(...)`) без доменного агрегата и маппера. `Protocol` — в `application/ports.py`, методы вызывают `uow.require_active()`, событие — через `uow.add_event`. Когда у записи появляется правило, она становится агрегатом.

**Repository агрегата:**

- Один репозиторий на корень агрегата. `Protocol` — в `application/ports.py`, реализация `Sql<Имя>Repository` — в `infrastructure/repositories.py`.
- Возвращает доменные объекты. ORM-классы (`<Имя>Row`) не покидают `infrastructure`. Маппинг — чистые функции `to_domain(row)` и `apply(aggregate, row)` в `infrastructure/mappers.py`.
- Методы — только те, что нужны use cases: `get` (нет записи — `NotFoundError`), `get_for_update` (`SELECT … FOR UPDATE`, где инвариант требует сериализации, например лимит 5 откликов), `add`, `save` и узкие `find_…`, если их требует инвариант. Generic `BaseRepository[T]` с CRUD по всем полям и методы «для экрана» не заводим.
- **Загрузка.** `get` — явный `select(...)` с `selectinload` для связей и `execution_options(populate_existing=True)`. `session.get(..., options=...)` не подходит: если строка уже в identity map, опции не применяются, связи не догружаются, и маппер падает на `lazy="raise"`. Связи ORM — `lazy="raise"`, агрегат загружается целиком одним методом.
- **Отслеживание.** `get`, `get_for_update`, `add` и `save` вызывают `uow.track(aggregate)`. Так UoW забирает события и ловит забытый `save` (§4); репозиторий вне активного UoW падает.
- **Сохранение.** `add` и `save` переносят состояние в строку, вставляют строки `status_history` из `pull_history()` и делают `await session.flush()`. На flush всплывают `IntegrityError` и `StaleDataError`, поэтому ошибки ограничений переводятся здесь, по имени constraint (`uq_responses_job_id_performer_id` → `AlreadyRespondedError`), а не при COMMIT. Неизвестное ограничение пробрасывается как есть.
- Бизнес-правил в репозитории нет: ни проверок статуса, ни лимитов, ни прав. Он загружает, сохраняет и переводит нарушения ограничений БД в доменные ошибки.
- **Optimistic locking.** `version` — `version_id_col` ORM с `version_id_generator=False`: новую версию ставит репозиторий, и `save` увеличивает её при каждом вызове. Поэтому версия корня растёт и тогда, когда изменились только дочерние строки (отклики, медиа), и конкурентная правка подагрегата ловится. После flush репозиторий передаёт версию в агрегат методом `mark_persisted(version=...)`, и use case возвращает клиенту актуальный ETag. Сверку с `If-Match` делает агрегат (`ensure_version`). Для каждого агрегата с подагрегатами есть тест «изменение подагрегата увеличивает версию корня».
- **Soft delete:** `get` не возвращает удалённые записи. Удаление — метод агрегата (`job.delete(now)`), SQL `DELETE` в прикладном коде не пишем.

```python
# modules/jobs/application/ports.py
class JobRepository(Protocol):
    async def get(self, job_id: JobId) -> Job: ...
    async def get_for_update(self, job_id: JobId) -> Job: ...
    async def add(self, job: Job) -> None: ...
    async def save(self, job: Job) -> None: ...


# modules/jobs/infrastructure/repositories.py
class SqlJobRepository(JobRepository):
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def get(self, job_id: JobId) -> Job:
        stmt = (select(JobRow)
                .where(JobRow.id == job_id, JobRow.deleted_at.is_(None))
                .options(selectinload(JobRow.media))
                .execution_options(populate_existing=True))
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise JobNotFoundError(job_id=job_id)
        job = to_domain(row)
        self._uow.track(job)                               # снимок для проверки забытого save
        return job

    async def save(self, job: Job) -> None:
        row = await self._session.get(JobRow, job.id)    # обычно из identity map
        if row is None:
            raise JobNotFoundError(job_id=job.id)
        apply(job, row)                                  # перенос состояния
        row.version = job.version + 1                    # версия корня растёт при любом save
        self._session.add_all(to_history_rows(job.id, job.pull_history()))
        try:
            await self._session.flush()                  # IntegrityError и StaleDataError — здесь
        except IntegrityError as err:
            raise_domain_error(err, JOB_CONSTRAINTS)     # NoReturn: доменная ошибка или исходная
        job.mark_persisted(version=row.version)
        self._uow.track(job)                             # новый снимок после сохранения
```

**Query-сервисы:**

- `Protocol` `<Сущность>Query` в `application/ports.py`, реализация `Sql<Сущность>Query(SqlQuery)` в `infrastructure/queries.py`. Внутри — SQLAlchemy Core `select()`, на выходе frozen dataclass (read-DTO), пагинация через `Page` (keyset по умолчанию, [§8.4](../ARCHITECTURE.md#84-пагинация-фильтры-сортировка)).
- Query-сервис джойнит только таблицы своей схемы.
- **Проектор** обновляет read-model (например, `search.specialist_index`). Порт `<Сущность>Projector` лежит в application, реализация в infrastructure делает идемпотентный upsert.

### 6. Фасад модуля (`api.py`)

- `api.py` — контракт модуля, а не реализация. В нём `Protocol` `<Модуль>Api`, DTO (frozen dataclass) и реэкспорт публичных ошибок из `errors.py`. Импортирует только stdlib, `errors.py` своего модуля, `platform/kernel` и `platform/contracts`.
- DTO фасадов используют типизированные ID из `platform/kernel` (`JobId`, `UserId`), а не голый `UUID`.
- Реализация — `application/facade.py`, класс `<Модуль>Facade`. `di.py` регистрирует его как провайдер `<Модуль>Api`.
- `application` другого модуля зависит от `<Модуль>Api`. В тестах use case его заменяет фейк (§11). При выделении модуля в сервис его заменяет HTTP-клиент с тем же протоколом ([§5.6](../ARCHITECTURE.md#56-как-модули-будут-выделяться-позже)).
- Методы двух видов: запросы (DTO через query-сервисы) и команды (требуют активного UoW, §4). Фасад не отдаёт наружу доменные объекты и ORM.
- Фасад вызывают только сверху вниз по DAG. BFF-роутеры `interfaces/http/views` могут вызывать любой фасад ([§5.2](../ARCHITECTURE.md#52-правила-модульности) п. 7), но по очереди (§4).

```python
# modules/deals/api.py — всё, что видят другие модули
from app.modules.deals.errors import DealNotFoundError as DealNotFoundError   # публичная ошибка


@dataclass(frozen=True, slots=True, kw_only=True)
class AgreedDealIn:
    job_id: JobId
    response_id: ResponseId
    client_id: UserId
    performer_id: UserId
    title_snapshot: str


class DealsApi(Protocol):
    async def create_agreed(self, data: AgreedDealIn) -> DealId:
        """Создаёт сделку agreed в транзакции вызывающего: нужен активный UoW."""
        ...

    async def get_summary(self, deal_id: DealId) -> DealSummary | None: ...


# modules/deals/application/facade.py
class DealsFacade(DealsApi):
    async def create_agreed(self, data: AgreedDealIn) -> DealId:
        self._uow.require_active()                       # свою транзакцию не открывает
        deal = Deal.agree_from_response(
            job_id=data.job_id, response_id=data.response_id, client_id=data.client_id,
            performer_id=data.performer_id, title_snapshot=data.title_snapshot,
            now=self._clock.now(),
        )
        await self._deals.add(deal)
        return deal.id
```

Поля передаются явно: `**asdict(data)` превращает вложенные dataclass в `dict` и отключает проверку аргументов в mypy, поэтому в `domain` и `application` он запрещён (§15).

### 7. Синглтоны и DI (dishka)

- **Синглтон — это объект dishka со `Scope.APP`.** Он создаётся один раз на процесс и закрывается финализатором при остановке. Заводим его, только если объект держит дорогой или общий ресурс: пул, соединение, HTTP-сессию, ключи. Остальное — REQUEST scope или обычные функции без DI.

| Scope | Что | Кто создаёт |
|---|---|---|
| `APP` | Настройки и их группы, конфиги модулей (`<Модуль>Config`), `AsyncEngine` с пулом, `async_sessionmaker(expire_on_commit=False)`, клиент Valkey, aiogram `Bot` как HTTP-клиент, Procrastinate `App`, ключи JWT (`kid`), S3-клиент, `httpx.AsyncClient` и адаптеры AI с circuit breaker, rate limiter, `Clock`, каталоги переводов, реестр подписчиков событий | `platform/di.py`, `modules/<x>/di.py` |
| `REQUEST` | `AsyncSession`, `UnitOfWork`, `JobQueue` на соединении сессии, репозитории, query-сервисы, use cases, фасады (`<Модуль>Api`) | `platform/di.py` и `modules/<x>/di.py` |
| `REQUEST` | `Principal`, локаль запроса | Провайдер интерфейса: `interfaces/http/di.py`, `interfaces/bot/di.py` |

- **Один контейнер на процесс.** Его собирает `entrypoints/_wiring.py::make_container(...)` из `PlatformProvider`, провайдеров всех модулей и провайдера интерфейса; там же собирается реестр подписчиков событий. Провайдеры platform и модулей одинаковы для `web`, `bot` и `worker` ([ADR-0004](0004-backend-stack-fastapi-sqlalchemy.md)).
- **Провайдер интерфейса у каждого процесса свой.** В `web` он берёт `Principal` из JWT (через `Request` от `FastapiProvider`), локаль — из `Accept-Language`. В `bot` он находит `Principal` по `telegram_id` через фасад `identity` (данные апдейта — от `AiogramProvider`), локаль — из профиля. У `worker` такого провайдера нет: use case получает `actor_id` в команде, и `application` с `infrastructure` от `Principal` не зависят. dishka проверяет граф при сборке контейнера, поэтому лишняя зависимость от `Principal` упадёт при старте воркера, а не в рантайме.
- Scope открывают интеграции dishka с FastAPI и aiogram, а в задачах — обёртка `platform/queue` вручную.
- **Зависимости приходят через конструктор.** `FromDishka[...]` и `@inject` встречаются только во входных адаптерах: роутерах, хендлерах бота, обёртке задач. `application` и `infrastructure` о контейнере не знают. Единственное чтение контейнера из запроса — хелпер SQLAdmin в `platform/http/admin.py` (§4).
- **Изменяемое состояние внутри APP-объекта** допустимо только техническое и безопасное для asyncio: пул, счётчики circuit breaker, кэш с TTL. Бизнес-состояние в памяти процесса не храним: процессов `web` несколько, его место — PostgreSQL или Valkey.
- **Декларативные реестры на уровне модуля разрешены:** `APIRouter`, aiogram `Router`, Procrastinate `Blueprint`, SQLAlchemy `MetaData` и `DeclarativeBase`, dishka `Provider`, константы `TaskRef`, `structlog.get_logger()`. Они не держат соединений и собираются в точке сборки.
- **Реестр подписчиков событий** собирает `entrypoints/_wiring.py` из подписок в `tasks.py` модулей, и подключают его все три entrypoint: события диспетчеризуются при commit и в `web`, и в `bot`, а не только в воркере. `interfaces/worker` только регистрирует задачи и периодические задачи Procrastinate. Интерфейсные пакеты друг друга не импортируют.

```python
# platform/di.py (сокращённо)
class PlatformProvider(Provider):
    settings = from_context(provides=Settings, scope=Scope.APP)

    @provide(scope=Scope.APP)
    async def engine(self, db: DbSettings) -> AsyncIterator[AsyncEngine]:
        engine = create_async_engine(db.dsn.get_secret_value(), pool_size=db.pool_size)
        yield engine
        await engine.dispose()

    @provide(scope=Scope.APP)
    def session_maker(self, engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
        return async_sessionmaker(engine, expire_on_commit=False)

    @provide(scope=Scope.REQUEST)
    async def session(self, maker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    uow = provide(SqlAlchemyUnitOfWork, scope=Scope.REQUEST, provides=UnitOfWork)


# modules/jobs/di.py
class JobsProvider(Provider):
    scope = Scope.REQUEST
    jobs = provide(SqlJobRepository, provides=JobRepository)
    feed = provide(SqlJobFeedQuery, provides=JobFeedQuery)
    close_job = provide(CloseJob)
    facade = provide(JobsFacade, provides=JobsApi)

    @provide(scope=Scope.APP)
    def config(self, s: JobsSettings) -> JobsConfig:          # Pydantic-настройки → dataclass
        return JobsConfig(max_responses=s.max_responses)


# modules/jobs/http/router.py — роутер тонкий, commit не делает
router = APIRouter(prefix="/jobs", tags=["jobs"], route_class=DishkaRoute)

@router.post("/{id}/close")
async def close_job(id: UUID, body: CloseJobIn, if_match: IfMatch,
                    principal: FromDishka[Principal], close: FromDishka[CloseJob]) -> JobRefOut:
    ref = await close(CloseJobCommand(actor_id=principal.user_id, job_id=JobId(id),
                                      reason=body.reason, expected_version=if_match))
    return JobRefOut.model_validate(ref, from_attributes=True)
```

Запрещено:

```python
settings = Settings()                       # глобальный конфиг на уровне модуля
valkey = Redis.from_url(URL)                # клиент на уровне модуля

@lru_cache
def get_bot() -> Bot: ...                   # скрытый синглтон

class SingletonMeta(type): ...              # метакласс-синглтон, __new__ с _instance

container.get(JobRepository)                # service locator в прикладном коде
```

### 8. Другие паттерны: когда применять

| Паттерн | Где живёт | Применяем | Не применяем |
|---|---|---|---|
| **Facade** | `api.py` + `application/facade.py` | Любой вызов модуля из другого модуля | Внутри модуля: там use cases вызываются напрямую |
| **Ports and Adapters** | Порт в `application/ports.py` или `platform/*/port.py`, адаптер в `infrastructure` или `platform/*` | Каждый внешний сервис: БД, очередь, S3/R2, Telegram, OpenAI, Anthropic, поиск, `Entitlements`, время. Для внешних сервисов (Telegram, S3/R2, AI, `Clock`) есть фейк; БД и очередь в тестах настоящие | Чистые вычисления без I/O |
| **Strategy / цепочка** | `application` или `domain` | Взаимозаменяемые шаги одного процесса: проверки модерации (правила → omni-moderation → LLM), шаги разбора поискового запроса, каналы доставки уведомлений | Одна реализация без планов на вторую |
| **Factory** | Именованный конструктор агрегата (`Deal.agree_from_response(...)`); класс-фабрика в `domain` — если на вход нужны данные нескольких источников | Создание агрегата с инвариантами | Простые объекты: хватает конструктора dataclass |
| **Domain Events** | Классы в `platform/contracts/events`, запись в агрегате, постановка в UoW (§4) | Побочные эффекты в других модулях и асинхронные реакции. Подписчик идемпотентен ([§12.4](../ARCHITECTURE.md#124-идемпотентность-и-надёжность)) | Синхронный инвариант в одной транзакции: он идёт через фасад |
| **State machine** | `domain`, одинаковая форма (§2) | Каждая сущность со статусом | — |
| **Policy** | `domain/policies.py` | Права и правила «можно ли», общие для нескольких use cases | Проверка формата ввода: это валидация схемы |
| **Specification** | `domain` | Только если один предикат нужен и в памяти, и в SQL, и дублирование уже мешает | По умолчанию не заводим |
| **DTO** | HTTP-схемы — Pydantic в `http/schemas.py`; команды, результаты, DTO фасадов и payload задач — frozen dataclass (payload валидирует обёртка задач через `TypeAdapter`, §3) | Любая граница слоя или модуля | Внутри domain |
| **Optimistic locking** | `VersionedAggregate.version` + `If-Match` (§5) | Агрегаты, которые правят двое (заявка, профиль, сделка) | Append-only данные (сообщения, аудит) |
| **Circuit breaker** | Адаптеры внешних AI и KYC | Недоступный сервис не должен вешать конвейер: контент уходит в ручную очередь | Внутренние вызовы |

### 9. Ошибки: одна модель на HTTP, бот и задачи

- **Исключения, без Result-типов.** FastAPI, aiogram и Procrastinate построены на исключениях. Result-типы в Python не поддержаны языком и дали бы второй стиль.
- **Базовые классы** лежат в `platform/kernel/errors.py` и про HTTP не знают. Конкретная ошибка — класс в `errors.py` модуля с `code: ClassVar[str]` (snake_case, стабильный, уникальный на проект) и именованными параметрами для текста.
- **Отображение — в одном месте на интерфейс:** `interfaces/http/errors.py` (RFC 9457, [§8.3](../ARCHITECTURE.md#83-формат-ошибок-rfc-9457-problem-details)), middleware бота, обёртка задач в `platform/queue`.
- **Текст для человека** берётся из i18n по ключу `errors.<code>` (ru, sr_Cyrl, sr_Latn); `detail` локализуется по `Accept-Language`.

| Базовый класс | HTTP | Бот | Задача |
|---|---|---|---|
| `NotFoundError` | 404 | Сообщение «не найдено» | Завершить без повтора, warning |
| `ForbiddenError` | 403 | Локализованное сообщение | Без повтора |
| `RestrictedError` | 403, `code=restricted`, `restriction`, `until` | Сообщение о санкции | Без повтора |
| `ConflictError` (в т. ч. запрещённый переход, лимит) | 409 | Сообщение по `code` | Без повтора: состояние уже другое |
| `ConcurrentModificationError` (`StaleDataError` ORM: строку изменили параллельно) | 409, `code=concurrent_modification` | «Данные обновились, повторите» | Повтор |
| `StaleVersionError` (не совпал `If-Match`) | 412 | — (If-Match есть только в HTTP) | — |
| `DomainValidationError` | 422 | Подсказка | Без повтора, error |
| `RateLimitedError` | 429 + `Retry-After` | «Слишком часто» | Повтор с задержкой |
| `ExternalServiceError` (таймаут, 5xx внешнего сервиса) | 503 без деталей, `trace_id` | «Временная ошибка» | Повтор с бэкоффом |
| Прочие исключения, в т. ч. ошибки программиста (`UnsavedAggregateError`, `NestedTransactionError`, `WriteOutsideUnitOfWorkError`) | 500 без деталей, `trace_id`, Sentry | Общий текст | Повтор, затем `failed` и алерт |

- Задача-подписчик, увидевшая, что состояние уже изменилось, завершается без ошибки. Так выглядит идемпотентность, а не сбой.
- Запрещено: `except Exception: pass`, перехват ради возврата `None`, `HTTPException` в `application` или `domain`.

### 10. Единообразие: имена, типы, стиль, логи, настройки

| Что | Правило | Пример |
|---|---|---|
| Файлы и пакеты | `snake_case`, одно понятие — один файл | `use_cases/accept_response.py` |
| Агрегат, VO, перечисление | Существительное в единственном числе | `Job`, `Money`, `JobStatus` |
| Use case | Глагол + объект; файл называется так же | `AcceptResponse` в `accept_response.py` |
| Команда | `<UseCase>Command`, в файле своего use case | `AcceptResponseCommand` в `accept_response.py` |
| Результат, read-DTO, payload задачи | `<Сущность>Ref` / `<Сущность>Result` / `<Сущность>View` / `<Задача>Payload`, в `application/dto.py` | `DealRef`, `JobCardView`, `DeleteObjectPayload` |
| Ссылка на задачу | Константа `TaskRef` в `application/ports.py`, имя `UPPER_SNAKE` | `DELETE_OBJECT` |
| Конфиг модуля | `<Модуль>Config` в `application/config.py` | `JobsConfig` |
| Порт | Роль + `Repository` / `Query` / `Projector` / `Port` | `JobRepository`, `JobFeedQuery`, `StoragePort` |
| Реализация порта | Технология + имя порта; фейк — `Fake<Имя>` | `SqlJobRepository`, `R2Storage`, `FakeTelegram` |
| Фасад | `<Модуль>Api` (контракт), `<Модуль>Facade` (реализация) | `DealsApi`, `DealsFacade` |
| ORM-класс | `<Сущность>Row`, чтобы не путать с доменом | `JobRow` |
| HTTP-схемы | `<Имя>In` / `<Имя>Out`. Суффикс `Response` не используем: в домене это «отклик» | `CloseJobIn`, `ResponseOut` |
| Ошибка | `<Суть>Error` в `errors.py` модуля, `code` в snake_case | `JobNotOpenError`, `job_not_open` |
| Событие | Прошедшее время; тип `<модуль>.<Имя>`, `schema_version` | `JobPublished`, `jobs.JobPublished` v1 |
| Задача, периодическая задача | `<модуль>.<глагол>_<объект>` ([§12.3](../ARCHITECTURE.md#123-периодические-задачи)) | `jobs.match_alerts`, `jobs.expire_jobs` |
| Эндпоинт | `/api/v1`, ресурсы во множественном числе, `kebab-case`, переход — подресурс-глагол ([§8.1](../ARCHITECTURE.md#81-стиль-и-соглашения)) | `POST /jobs/{id}/close`, `/me/job-alerts` |
| `operationId` | `<модуль>_<имя функции роутера>`: из него orval делает имена хуков | `jobs_close_job` → `useJobsCloseJob` |
| Миграция | `<модуль>_NNNN_<slug>.py`, ревизия `<модуль>_NNNN` | `jobs_0007_add_alerts_area.py` |
| Ограничения и индексы БД | Naming convention `DeclarativeBase`; по имени constraint репозиторий переводит ошибку (§5) | `pk_jobs`, `uq_responses_job_id_performer_id` |
| Лог-событие | `snake_case`, `<объект>_<что случилось>` | `job_published` |
| Переменная окружения | `<ГРУППА>_<КЛЮЧ>` | `TELEGRAM_BOT_TOKEN`, `DB_DSN` |
| Feature flag | `<модуль>.<флаг>` | `goods.enabled` |
| `callback_data` бота | `<действие>:<id>[:<арг>]`, ≤ 64 байт | `respond:<job>:<tpl>` |

**Язык.** Идентификаторы — английские. Комментарии и docstring — на русском, как документация. `code` ошибок, имена лог-событий и задач — английский snake_case.

**Python:**
- Синтаксис 3.14: generics по PEP 695 (`class Page[T]`), `StrEnum`, `Self`, `typing.override`. `from __future__ import annotations` не используем: в 3.14 аннотации и так ленивые, а FastAPI, Pydantic и dishka читают их в рантайме.
- Весь I/O асинхронный. Domain синхронный (§2). Блокирующие библиотеки (boto3, Pillow, ffmpeg) вызываются только внутри адаптеров через `asyncio.to_thread` или подпроцесс.
- **Типы:** mypy `strict = true` на весь `src/app`. Послабления — только для `tests/`, `migrations/` и сторонних пакетов без типов. `Any` и `# type: ignore[код]` — только с комментарием о причине. Pyright в CI не используем: источник правды один.
- **Линтер и форматтер** — ruff, других форматтеров нет:

```toml
[tool.ruff]
target-version = "py314"
line-length = 100

[tool.ruff.lint]
select = ["E", "W", "F", "I", "B", "UP", "SIM", "C4", "RUF", "ASYNC", "S", "PT", "N",
          "DTZ", "T20", "ERA", "TID", "RET", "ARG", "FBT", "BLE", "G", "PERF", "PLE"]

[tool.ruff.lint.flake8-tidy-imports.banned-api]
"datetime.datetime.now".msg = "Время — только через порт Clock"
"datetime.datetime.utcnow".msg = "Время — только через порт Clock"
"uuid.uuid4".msg = "Идентификаторы — UUIDv7: platform.kernel.new_id()"
"os.getenv".msg = "Настройки — только platform/settings.py"
"os.environ".msg = "Настройки — только platform/settings.py"
"requests".msg = "Синхронный HTTP запрещён: httpx.AsyncClient в адаптере"

[tool.ruff.lint.per-file-ignores]
"**/tests/**" = ["S101", "ARG", "FBT"]
"src/app/platform/settings.py" = ["TID251"]
"src/app/platform/kernel/clock.py" = ["TID251"]
```

**Логи.** structlog, `log = structlog.get_logger(__name__)`. Имя события — константа в snake_case, контекст — именованные аргументы, f-строк в имени события нет. `print` запрещён. Уровни: `info` — бизнес-событие, `warning` — обработанная аномалия, `error` — сбой, который требует внимания и уходит в Sentry. `user_id` — внутренний UUID. ПД, `initData`, токены и тексты сообщений не логируем, маскирующий процессор ([§13.5](../ARCHITECTURE.md#135-секреты-логи-бэкапы)) — страховка, а не разрешение.

**Настройки.** Только `platform/settings.py` на pydantic-settings: группы (`DbSettings`, `TelegramSettings`, `JobsSettings`, …) с `env_prefix`, секреты — `SecretStr`. Объекты групп приходят через DI (APP) в `platform`, адаптеры и `di.py`. `application` получает не их, а frozen dataclass `<Модуль>Config` (§3): иначе транзитивный запрет Pydantic в `pure-core` упадёт. Новая настройка появляется в `backend/.env.example` в том же шаге, это сверяет архитектурный тест. Значения секретов в git не попадают.

**i18n.** В gettext-каталогах backend `msgid` — стабильный ключ (`jobs.notify.job_matched.title`), а не фраза. Тогда ru и sr_Cyrl — равноправные переводы, и правка русского текста не ломает сербский каталог ([ADR-0013](0013-i18n-multilingual-content.md)). На фронте ключи i18next — `<namespace>:<фича>.<элемент>`, тексты ошибок — `errors:<code>`, общие с `code` из API.

### 11. Тесты

| Уровень | Что проверяем | Где | Чем | Объём |
|---|---|---|---|---|
| Unit: domain | Агрегаты, state machine, политики, формулы | `modules/<x>/tests/unit` | pytest, без I/O | Больше всего |
| Use cases и фасады | Результат, состояние в БД, выпущенные события и поставленные задачи, ошибки | `modules/<x>/tests/integration` | pytest-asyncio, настоящий PostgreSQL, транзакция на тест с откатом, фейки внешних сервисов | На каждый use case |
| Адаптеры | Репозитории (round-trip), query-сервисы, проекторы, миграции, UoW + очередь, Garage, Valkey | `modules/<x>/tests/integration`, `backend/tests/integration` | testcontainers на нашем образе PostGIS | На каждый адаптер |
| Конкурентность | `FOR UPDATE`, лимит откликов, уникальность, версии | `modules/<x>/tests/integration` | Настоящие commit в двух соединениях, очистка таблиц после теста | Где инвариант требует сериализации |
| API | Каждый публичный эндпоинт: успех, права, валидация | `modules/<x>/tests/api` | httpx `AsyncClient`, реальная БД | 3+ на эндпоинт |
| Контрактные | OpenAPI | `backend/tests/contract` | schemathesis, oasdiff | Вся схема |
| E2E | Сквозные цепочки: use case → событие → задача → уведомление | `backend/tests/e2e` | Воркер in-process | 5–10 сценариев |
| Архитектурные | §15 | `backend/tests/architecture` | pytest + `ast` | Весь код |

- **Use cases — на настоящем PostgreSQL.** Один контейнер testcontainers на сессию pytest, миграции один раз. На каждый тест открывается соединение с внешней транзакцией, сессия присоединяется к ней (`join_transaction_mode="create_savepoint"`): commit в UoW фиксирует только savepoint, а в конце теста внешняя транзакция откатывается. Тест занимает миллисекунды и заодно проверяет UoW, мапперы, ограничения БД и постановку задач. Поставленные задачи видны хелпером `queued_tasks(session)` из `platform/testing`.
- **Фейки — только для внешнего.** `platform/testing`: `FakeClock`, фейки Telegram, S3/R2 и AI. `modules/<x>/tests/fakes.py`: фейки фасадов других модулей по их `Protocol`, чтобы тест модуля не готовил данные в чужих схемах. Атомарность между модулями (отклик → сделка) проверяют API- и E2E-тесты на полном контейнере. Фейковых UoW и in-memory репозиториев нет.
- **Round-trip репозитория:** `add` → `get` на реальной БД, сравнение через `assert_same_state` (§2).
- **Данные для тестов:** билдеры для domain (`a_job(status=JobStatus.PUBLISHED)`), polyfactory для DTO и HTTP-схем.
- SQLite запрещён. Покрытие domain и application ≥ 80% ([§2.4](../ARCHITECTURE.md#24-нефункциональные-требования-slo)).

### 12. Шаблон модуля и генератор

- **Эталон** — модуль `identity` после шага identity-core (шаги [0.15a–0.15c](../DEVELOPMENT_PLAN.md#015-модуль-identity--эталонный-срез-015a015c) плана, первый сквозной срез этапа 0). С него снимается шаблон [copier](https://copier.readthedocs.io/) `backend/templates/module/` и шаблон `backend/templates/use_case/` (файл use case с командой и классом, тест на реальной БД, строка в `di.py`).
- **Новый модуль или use case создаётся командой, а не копированием:** `uv run copier copy backend/templates/module backend/src/app/modules/<name>` (из корня — обёртка `make new-module NAME=<name>`). Шаблон создаёт только обязательные слои (§1); входные адаптеры добавляются, когда нужны.
- `copier update` не используем: на 15 модулях он даёт конфликты слияния при каждой правке шаблона. Если шаблон поменялся, существующие модули правятся отдельным явным шагом.
- Структуру проверяет архитектурный тест: даже созданный руками модуль обязан иметь обязательные файлы и слои.

### 13. Фронтенд

Те же принципы в терминах [ADR-0012](0012-mini-app-frontend-and-mobile-path.md): хуки `api-client` играют роль репозитория и query-сервиса, `packages/platform` — порт с адаптерами, а `QueryClient`, i18n, Sentry и платформа — синглтоны точки сборки.

```text
apps/tma/src/
├── app/                        # точка сборки: providers (QueryClient, i18n, platform, Sentry), router, error boundary
├── routes/                     # файлы TanStack Router: связывают URL и экран, логики нет
├── features/
│   └── jobs/
│       ├── s15-job-detail/     # одна папка — один экран; код экрана в имени
│       │   ├── JobDetailScreen.tsx      # экран: UI и склейка с packages/platform
│       │   ├── store.ts                 # Zustand, только UI-состояние (если нужно)
│       │   ├── JobDetailScreen.test.tsx
│       │   └── index.ts                 # публичный экспорт фичи
│       └── shared/             # общее внутри группы экранов
└── main.tsx

packages/hooks/src/jobs/        # headless-хуки сценариев: их переиспользует Expo (этап 2)
├── useJobDetail.ts             # хуки api-client + правила packages/domain, без DOM и Telegram
└── useJobDetail.test.ts
```

| Тема | Правило |
|---|---|
| Данные | Только хуки `packages/api-client` (orval). `fetch` напрямую — только в mutator клиента |
| Хуки сценариев | Хук без DOM и Telegram (api-client + `packages/domain`) — в `packages/hooks/<фича>`. В `features/` остаются экран, UI-стор и склейка с `packages/platform` |
| Состояние | Серверное — TanStack Query; UI — Zustand-стор фичи; фильтры и сортировка — search params роутера; формы — React Hook Form + Zod |
| Telegram | Только через `packages/platform`; `@tma.js/*` разрешён только в нём |
| UI | Только компоненты `packages/ui-web` на токенах `packages/design-tokens` (источник — утверждённый `ui.css`). Hex-цвета и произвольные значения в классах не пишем, inline-стили — только для раскладки |
| Тексты | Только `t()`; литералы в JSX запрещены |
| Бизнес-правила | `packages/domain` (чистый TypeScript: статусы, счётчик мест, бакеты бюджета, форматирование денег) |
| Границы | `routes → features → packages`; фичи не импортируют друг друга, общее выносится в `packages/hooks` или `ui-web` |
| Синглтоны | `QueryClient`, экземпляр i18n, Sentry, адаптер платформы создаются один раз в `app/` и передаются провайдерами React; фичи их не импортируют |
| Имена | Компоненты `PascalCase.tsx`, экран — `<Имя>Screen`, хуки `useX`, сторы `useXStore`, папки `kebab-case` с кодом экрана |
| Типы | TypeScript `strict` + `noUncheckedIndexedAccess`; `any` — только с комментарием |
| Тесты | Vitest (unit и компоненты), MSW из orval, Playwright со скриншотами 390×844 |

```ts
// packages/hooks/src/jobs/useJobDetail.ts
export function useJobDetail(jobId: string) {
  const job = useJobsGetJob(jobId);                          // сгенерировано orval
  const slots = job.data ? responseSlots(job.data) : null;   // packages/domain: «осталось 2 места»
  return { job, slots };
}
```

```js
// packages/config/eslint — фрагмент (flat config)
const apiOnly = { group: ['axios', 'ky'], message: 'API — только хуки packages/api-client' };

export default [
  { rules: {
      'no-restricted-imports': ['error', { patterns: [
        { group: ['@tma.js/*'], message: 'Telegram — только через packages/platform' }, apiOnly,
      ] }],
      'no-restricted-globals': ['error', { name: 'fetch', message: 'API — только хуки packages/api-client' }],
      'i18next/no-literal-string': 'error',
      // границы routes → features → packages: eslint-plugin-boundaries
  } },
  { files: ['packages/platform/**'],            // единственное место, где разрешён @tma.js
    rules: { 'no-restricted-imports': ['error', { patterns: [apiOnly] }] } },
  { files: ['packages/api-client/src/mutator.ts'],
    rules: { 'no-restricted-globals': 'off' } },
];
```

### 14. Антипаттерны

| Запрещено | Почему | Вместо этого |
|---|---|---|
| Active Record в домене (`job.save()`, сессия внутри сущности) | Домен зависит от БД, тесты без БД невозможны | Репозиторий + UoW |
| Service locator (`container.get(...)` в прикладном коде) | Зависимости скрыты, класс не собрать в тесте | Конструктор + DI |
| God-сервис (`JobService` на 40 методов) | Всё связано со всем, ревью невозможно | Один use case — один класс |
| Бизнес-логика в роутере, хендлере бота, задаче или админке | Правило срабатывает только в одном канале | Use case + domain |
| Прямой доступ к чужой схеме БД: JOIN, `SELECT` или запись в `other_module.*` | Ломает границы и выделение модулей | Фасад, события, read-model `search` |
| ORM-классы за пределами `infrastructure` | Ленивые загрузки и сессия протекают в логику | Доменные объекты и DTO |
| `utils.py`, `helpers.py`, `common.py`, `misc.py` | Свалка без владельца | Модуль с именем понятия; сквозное — в подпакет `platform` с ясным именем |
| Generic `BaseRepository[T]` с CRUD по всем полям | Обходит инварианты агрегата | Узкие методы, которые нужны use cases |
| Глобальные изменяемые объекты, клиенты на уровне модуля, `lru_cache` как синглтон | Скрытое состояние, тесты влияют друг на друга | `Scope.APP` в dishka |
| `commit` вне UoW, вложенные транзакции, savepoint'ы в модулях | Частичные фиксации, потерянные задачи | Один `async with uow` на команду |
| `asyncio.gather` и `TaskGroup` над фасадами, репозиториями и query-сервисами | Одна сессия на скоуп не допускает конкурентных запросов: плавающие ошибки под нагрузкой | Последовательные вызовы; параллельные внешние вызовы — внутри адаптера platform |
| Внешний вызов (Telegram, S3, AI) внутри `async with uow` | Запись остаётся при откате, любое ожидание держит соединение пула | Запись — задачей после commit, чтение — до блока |
| Изменение агрегата без `save` | Изменения и события молча теряются | `save` в use case; UoW бросает `UnsavedAggregateError` |
| `**asdict(dto)` в вызовах конструкторов и методов | Вложенные dataclass становятся `dict`, mypy перестаёт проверять аргументы | Поля явно |
| Pydantic и фреймворки в `domain` и `application` | Нарушает ADR-0004 и чистоту слоёв | dataclass; Pydantic только на границах |
| Наивный `datetime`, `float` для денег, `uuid4` | Ошибки часовых поясов и округления, плохая локальность индексов | `Clock`, `Money`, UUIDv7 |
| Telegram ID вместо внутреннего `user_id` в логике и логах | Связывание с внешней идентичностью | Внутренний UUID; Telegram ID — только в `identity.auth_identities` |

### 15. Как контролируем

| Правило | Механизм | Когда |
|---|---|---|
| Слои модуля, DAG, «наружу только `api`» | import-linter (§1, [ADR-0002](0002-modular-monolith.md)) | pre-commit и CI |
| Чистые `domain`, `application`, `api`, `errors`, `platform/kernel`, порты | import-linter `forbidden` и разрешающий архитектурный тест: в `application` из сторонних только `structlog`, в остальных — только stdlib | CI |
| `commit`/`rollback` только в `platform/db` | Архитектурный тест (`ast`: вызовы `.commit(`/`.rollback(` вне `platform/db`) | CI |
| Нет `asyncio.gather`/`TaskGroup` в `application`, `interfaces/http/views` и входных адаптерах модулей; нет `**asdict(` в `domain` и `application` | Архитектурный тест (`ast`) | CI |
| Структура модуля и имена файлов, классов, задач, миграций | Архитектурный тест | CI |
| Уникальность `code` ошибок, ключи `errors.<code>` в ru и sr_Cyrl | Архитектурный тест | CI |
| Настройки ↔ `.env.example` | Архитектурный тест | CI |
| Граф DI | Тест: контейнер собирается для `web`, `bot` и `worker` | CI |
| `operationId` по правилу, ответы RFC 9457 в схеме | Тест по OpenAPI, schemathesis, oasdiff | CI |
| Типы и стиль | mypy strict, ruff check и format | pre-commit и CI |
| Миграции | Имя файла, одна head, `alembic check`, upgrade/downgrade | CI |
| Фронтенд | ESLint (boundaries, restricted imports и globals, i18next), `tsc` strict, перегенерация `api-client` без diff | CI |
| Остальное | Чек-лист в шаблоне PR и ревью владельца | Каждый шаг |

Отступление от правила оформляется явно: комментарий `# ADR-0020: исключение — <причина>` рядом с кодом и запись в `ignore_imports` `.importlinter`. Если исключений одного вида становится больше двух, пишется новый ADR.

Чек-лист в `.github/pull_request_template.md`:

```markdown
- [ ] Логика — в domain; use case только оркестрирует; роутер и хендлер тонкие
- [ ] Запись — через репозиторий (агрегат или простая запись), чтение — через query-сервис; транзакция — один `async with uow`
- [ ] Фасады, репозитории и query-сервисы вызываются по очереди, без `gather`
- [ ] Внешнее чтение — до `async with uow`, внешняя запись — задачей после commit
- [ ] Зависимости — через DI; глобальных объектов нет
- [ ] Ошибки — классы с `code` в `errors.py`; ключи `errors.<code>` есть в ru и sr_Cyrl
- [ ] События — в platform/contracts; подписчики идемпотентны
- [ ] Тесты: unit на domain; use case на реальной БД; API-тест на каждый новый эндпоинт (успех, права, валидация)
- [ ] Миграция `<module>_NNNN_<slug>`, expand/contract, `alembic check` без расхождений
- [ ] OpenAPI обновлён, api-client перегенерирован
- [ ] Новые настройки — в `.env.example`; секретов в diff нет
- [ ] Затронутые ADR указаны; отступления от ADR-0020 помечены
```

### 16. Что уточняется в других документах

| Документ | Было | Стало |
|---|---|---|
| ARCHITECTURE §5.5 | «Тонкий» вариант `geo` и `catalog`: запросы прямо из application, без domain | Структура одинакова во всех модулях. В тонких модулях `domain/` содержит только перечисления и VO; чтение идёт через query-сервис (`Protocol` в application, реализация в infrastructure); записи из прикладного кода нет |
| ARCHITECTURE §5.5, §6 | Состав модуля без `di.py`; `api.py` — фасад; внутри каждого модуля все слои, включая `http/`, `bot/`, `admin/`, `tasks.py` | Обязательны `api.py`, `errors.py`, `di.py`, `domain/`, `application/`, `infrastructure/`, `tests/`; входные адаптеры — по необходимости. `api.py` содержит контракт (`Protocol`, DTO, реэкспорт публичных ошибок из `errors.py`), реализация — `application/facade.py` |
| ARCHITECTURE §6 | `jobs/responses`, `jobs/alerts` | Подагрегаты — файлы внутри слоёв (`domain/response.py`, `use_cases/submit_response.py`); при росте — подпапки внутри слоя, а не подпакеты со своими слоями |
| ARCHITECTURE §6 | Состав `platform` | Добавлены `platform/kernel` (чистые типы, `AggregateRoot`, `Principal`, базовые ошибки, `Clock`), `platform/http` (хелперы роутеров модулей: `IfMatch`, курсор, идемпотентность, хелпер SQLAdmin; модули не импортируют `interfaces`), `platform/audit` (порт `AuditLog`), `platform/testing` (фейки внешних сервисов, хелперы тестовой БД). Порты подпакетов — в `port.py`. Провайдеры `Principal` и локали — в `interfaces/http/di.py` и `interfaces/bot/di.py` |
| ARCHITECTURE §6 (`interfaces/worker`, `entrypoints`) | Регистрация задач и подписок — в воркере | `interfaces/worker` регистрирует только задачи Procrastinate. Контейнер и реестр подписчиков собирает `entrypoints/_wiring.py` для всех трёх процессов: события диспетчеризуются при commit в `web` и `bot` тоже |
| ARCHITECTURE §6 (соглашения, тесты) | Unit-тесты domain и application лежат рядом с модулем | Unit-тесты — только domain; use cases и фасады тестируются на реальном PostgreSQL в откатываемой транзакции (§11) |
| ARCHITECTURE §5.8 | DTO фасада `goods` — frozen Pydantic | DTO всех фасадов — frozen dataclass с типизированными ID: `application` чужого модуля не должна тянуть Pydantic. JSON-схемы при выделении сервиса строятся через `pydantic.TypeAdapter` |
| ARCHITECTURE §16.4, ADR-0004 | mypy strict для domain и application | strict для всего `src/app`; послабления — только `tests`, `migrations` и пакеты без типов |
| ADR-0002 п. 3 | `import-linter` или `tach` | import-linter (как в ADR-0004) |
| ADR-0008 п. 2–3 | Use case регистрирует событие в UoW; `enqueue(task, payload, dedup_key)` | Событие записывает агрегат, репозиторий передаёт агрегат в UoW (`track`), при commit UoW собирает события; `uow.add_event` — только для событий без агрегата. Задача адресуется константой `TaskRef`, payload — frozen dataclass |
| ADR-0008 п. 6 | `queueing_lock` по ключу сущности | Постановка каждой задачи — под savepoint адаптера `JobQueue`; `AlreadyEnqueued` — успех (задача уже стоит), бизнес-транзакция не обрывается |
| research/03 §3.4 | ORM-модели служат сущностями в большинстве модулей | Доменные сущности отдельны во всех модулях с логикой записи; ORM — только в infrastructure (Data Mapper) |
| research/03 §3.4 | Repository — только для агрегатов с инвариантами | Две формы репозитория: агрегат (есть правило) и простая запись (командные методы без доменного агрегата). Любая запись из прикладного кода идёт через одну из них |
| research/03 §9.9 | `layers: api \| bot \| worker → application → domain`; фасад `public.py` | Слои из §1; фасад — `api.py` |

## Последствия

**Положительные**

- Все модули читаются одинаково. Владелец проверяет шаг по чек-листу, не разбираясь каждый раз в новой структуре.
- Domain тестируется без БД за миллисекунды. Use cases тестируются на настоящем PostgreSQL в откатываемой транзакции: заодно проверяются UoW, мапперы, ограничения и постановка задач, а фейки БД писать не нужно.
- Замена инфраструктуры — новый адаптер без правок use cases: outbox вместо прямой постановки в Procrastinate, другое хранилище, выделение модуля в сервис через HTTP-реализацию `<Модуль>Api`.
- Правила проверяют import-linter, mypy, ruff и архитектурные тесты. От памяти и внимательности ревьюера они не зависят.
- Самые вероятные ошибки кода, который пишет ИИ, ловятся механически: забытый `save` — `UnsavedAggregateError`, конкурентные вызовы в скоупе — архитектурный тест, зависимость от `Principal` в воркере — сборка контейнера.
- Скрытого глобального состояния нет: тесты изолированы, `web`, `bot` и `worker` собираются одним набором провайдеров platform и модулей.

**Отрицательные и риски**

| Риск | Смягчение |
|---|---|
| Больше кода: маппинг ORM ↔ domain, `Protocol` на каждый порт | Шаблон copier; мапперы — простые функции; у тонких модулей нет репозиториев; записи без правил — простая форма репозитория без агрегата; фейков репозиториев нет |
| Маппер отстаёт от ORM (забыли поле) | Round-trip тест каждого репозитория на реальной БД (`assert_same_state`) |
| Тесты use case на БД медленнее фейков | Один контейнер на сессию pytest, транзакция на тест с откатом; domain — без БД |
| mypy strict на всём коде замедлит первые недели (SQLAlchemy, aiogram, Procrastinate) | Overrides для пакетов без типов; через месяц после identity-core (шаги 0.15a–0.15c) — пересмотр, при необходимости откат до strict на domain, application и platform |
| Механика UoW (`track`, снимки, savepoint очереди) неочевидна новичку | Один механизм в `platform/db`, описан здесь; тесты platform-uow (шаг 0.10) фиксируют поведение; тест каждого use case проверяет выпущенные события |
| Маски и необязательные слои import-linter работают иначе, чем в наброске | Негативный тест на шаге `import-linter-dag` (0.2); запасной вариант — конфиг генерирует скрипт по списку модулей |
| Шаблон расходится с эталоном по мере развития | Правка шаблона — в том же шаге, что правка эталона; структуру сверяет архитектурный тест; существующие модули правятся явным шагом |
| Идемпотентность: процесс упал между commit use case и записью ответа | Ключ остаётся «в работе», повтор получает 409, дубля нет; ключ удалит `platform.idempotency_cleanup` |
| Правка справочника в SQLAdmin: событие теряется при падении между commit и постановкой | Идемпотентный реиндекс и ночной `search.reconcile_index` |
| ИИ-ассистент может «срезать углы» под давлением объёма | Архитектурные тесты в CI и чек-лист PR; шаг не считается готовым, пока проверки не зелёные |
| Командный метод фасада вызовут без активного UoW | `require_active()` падает сразу; тесты use case это ловят |

**Что сделать**

Номера — шаги [плана разработки](../DEVELOPMENT_PLAN.md); рабочие имена сопоставлены с номерами в §1 плана. Шаг считается выполненным, когда проходят перечисленные здесь тесты.

1. **backend-skeleton** — шаг [0.2](../DEVELOPMENT_PLAN.md#02-скелет-backend-и-границы-модулей): 15 пакетов модулей с обязательными слоями §1, подпакеты `platform/kernel`, `platform/contracts`, `platform/http`, `platform/audit`, `platform/testing`, `port.py` в подпакетах platform, заготовка `entrypoints/_wiring.py`; конфиги ruff и mypy из §10. Типы `platform/kernel` (`AggregateRoot`, `VersionedAggregate`, `aggregate_state`, `StatusChange`, `Principal`, базовые ошибки) и `assert_same_state` — шаг [0.7a](../DEVELOPMENT_PLAN.md#07-ядро-и-каркас-бд-07a07b); образец репозитория и query-сервиса по §5 — шаг [0.7b](../DEVELOPMENT_PLAN.md#07-ядро-и-каркас-бд-07a07b); раскладка тестов по §11 — шаг [0.5a](../DEVELOPMENT_PLAN.md#05-тестовый-контур-и-ci-backend-05a05b).
2. **import-linter-dag** — шаг [0.2](../DEVELOPMENT_PLAN.md#02-скелет-backend-и-границы-модулей): контракты §1 (маски, необязательные слои, слой `errors`) вместе с DAG из ADR-0002 и негативный тест (намеренно запрещённый импорт роняет проверку).
3. **platform-uow** — шаг [0.10](../DEVELOPMENT_PLAN.md#010-unit-of-work-доменные-события-порт-очереди), после спайка ADR-0008 (шаг [0.8](../DEVELOPMENT_PLAN.md#08-спайк-транзакционная-постановка-задач-procrastinate)): `UnitOfWork`, `SqlAlchemyUnitOfWork`, `SqlQuery`, `ProcrastinateJobQueue`, `TaskRef`. Роли `app` — `statement_timeout` и `idle_in_transaction_session_timeout` — задаёт `bootstrap.sql` в шаге [0.3](../DEVELOPMENT_PLAN.md#03-локальное-окружение-образ-postgresql-и-compose). Тесты: «rollback отменяет запись и задачу», «commit делает видимыми обе», «вложенный `async with` падает», «`require_active` без транзакции падает», «повторная постановка с тем же `dedup_key` не ломает бизнес-транзакцию», «после неудачного commit следующий `async with uow` в том же скоупе работает», «чтение до блока не мешает UoW», «query-сервис вне UoW возвращает соединение в пул», «забытый `save` → `UnsavedAggregateError`», «`StaleDataError` → 409», «`IntegrityError` по имени constraint → доменная ошибка». Обёртка задач (§3, §9) — шаг [0.12](../DEVELOPMENT_PLAN.md#012-воркер-и-периодические-задачи).
4. **platform-di** — шаг [0.11](../DEVELOPMENT_PLAN.md#011-di-контейнер-dishka): `PlatformProvider` по таблице §7, провайдеры интерфейсов `web` и `bot`; тесты «APP-объект создаётся один раз», «use case и фасад другого модуля получают одну сессию в одном REQUEST scope», «контейнер собирается для `web`, `bot` и `worker`».
5. **http-foundation** — шаги [0.13a–0.13b](../DEVELOPMENT_PLAN.md#013-http-каркас-013a013b): отображение ошибок по таблице §9, генератор `operationId` по правилу §10; идемпотентность по §4 и порт `AuditLog` — шаг [1.1](../DEVELOPMENT_PLAN.md#11-идемпотентность-аудит-флаги-client-config).
6. **identity-core** — шаги [0.15a–0.15c](../DEVELOPMENT_PLAN.md#015-модуль-identity--эталонный-срез-015a015c): первый модуль строго по этому ADR — эталон. После него, в шаге [0.15c](../DEVELOPMENT_PLAN.md#015-модуль-identity--эталонный-срез-015a015c), снять шаблоны copier `module` и `use_case`.
7. **Архитектурные тесты** `backend/tests/architecture` из таблицы §15 — шаг [0.15c](../DEVELOPMENT_PLAN.md#015-модуль-identity--эталонный-срез-015a015c), вместе с identity-core.
8. **Шаблон PR** `.github/pull_request_template.md` с чек-листом §15 — шаг [0.15c](../DEVELOPMENT_PLAN.md#015-модуль-identity--эталонный-срез-015a015c) (коммит — с согласия владельца).
9. **jobs-core** (первый агрегат с подагрегатами) — шаги [5.1](../DEVELOPMENT_PLAN.md#51-заявки-домен-и-api) (агрегат заявки) и [5.4](../DEVELOPMENT_PLAN.md#54-отклики-backend) (подагрегат «отклик»): тест «изменение отклика увеличивает версию заявки».
10. **FE-01** — шаг [0.16a](../DEVELOPMENT_PLAN.md#016-фронтенд-монорепо-и-ci-фронта-016a016b): ESLint-правила §13 (boundaries, restricted imports и globals, i18next, `@tma.js` только в `packages/platform`) и пакет `packages/hooks`; структура `app/`, `routes/`, `features/` — шаг [0.21a](../DEVELOPMENT_PLAN.md#021-каркас-mini-app-и-тестовый-контур-фронта-021a021b).
11. Добавить ADR-0020 в индекс [README.md](README.md) и сослаться на него из ARCHITECTURE §5.5 и §6. Эти файлы сейчас правят другие процессы, поэтому правку делает тот, кто их ведёт.
