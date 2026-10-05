# Карта Нови-Сада: тайлы, шрифты, спрайт (Q28, вариант A)

Ассеты для карты выбора точки при создании заявки (MapLibre GL + `pmtiles` в Mini App). Всё лежит
на наших серверах: без ключей API и сторонних хостов в рантайме (строгий CSP), координаты и
просмотр карты никуда, кроме наших серверов, не уходят. Источники — только официальные Protomaps:
ежедневная сборка `build.protomaps.com`, образ `protomaps/go-pmtiles`, репозиторий
`protomaps/basemaps-assets`. Бинарные тайлы в git не попадают (репозиторий публичный, тайлы
пересобираются), шрифты тоже — их ~2,4 МБ.

## Что собирает `build.py`

| Файл | Что | Размер |
|---|---|---|
| `novi-sad.pmtiles` | векторная подложка Protomaps v4 (MVT, gzip), зумы 0–15; рамка всех полигонов `backend/seeds/geo/novi-sad.geojson` плюс 5 км: `19.5563,45.1048,19.9956,45.3851` (34 × 31 км) | 12,9 МиБ |
| `fonts/{fontstack}/{range}.pbf` | глифы `Noto Sans Regular`, `Medium`, `Italic` (их берёт стиль `@protomaps/basemaps`), 9 диапазонов: латиница с расширениями, кириллица, диакритики, пунктуация, `№` | 2,4 МиБ, 27 файлов |
| `fonts/OFL.txt` | лицензия шрифтов | |
| `sprites/v4/{light,dark,white,grayscale,black}{,@2x}.{json,png}` | иконки POI и щиты стиля v4 | 0,17 МиБ, 20 файлов |
| `provenance.json` | входы сборки, исходный архив (версия схемы, дата, BLAKE3), заголовок PMTiles, атрибуция, лицензии, размер и sha256 каждого файла | |

Закреплено в `build.py`: сборка Protomaps `20260811` (схема 4.15.1), образ
`protomaps/go-pmtiles:v1.31.2@sha256:0657…`, коммит `basemaps-assets@028c18f` (git проверяет, что
получен ровно он). Готовый каталог с теми же входами и нетронутыми файлами не пересобирается.
Первый прогон — около минуты: вырезка ~20 с (`pmtiles extract` качает из планеты только нужные
диапазоны байт), шрифты и спрайт ~30 с. Нужны Docker и git.

## Запуск

```
make map-assets            # dev: apps/tma/public/map + VITE_MAP_ASSETS_URL=/map в apps/tma/.env
make dev-restart           # стенд пересоберёт Mini App уже с картой
make map-assets FORCE=1    # пересобрать
python3 scripts/map/build.py --out <каталог> [--build YYYYMMDD]   # в любой каталог
make map-upload ENV=stage  # в R2 stage — infra/runbooks/stage-bootstrap.md, раздел 7
```

## Где лежит и что грузит UI

| Окружение | `VITE_MAP_ASSETS_URL` | Откуда |
|---|---|---|
| dev | `/map` | `apps/tma/public/map`: Vite (dev-сервер и `vite preview` стенда, sirv) отдаёт с того же origin, Range — 206 |
| stage | `https://stage-cdn.<домен>/map/<версия>` | R2 `sosed-stage-media`, ключи `map/<версия>/…`, публичный домен бакета media |
| prod | `https://cdn.<домен>/map/<версия>` | R2 `sosed-prod-media` |

Почему не тот же origin на stage и prod: статика Workers (Mini App) на `Range` отвечает 200 и
целым файлом (в asset-worker нет обработки диапазонов), а `pmtiles` такой ответ отвергает. R2 за
своим доменом отдаёт 206, CORS бакета media уже пускает origin Mini App (`GET`, любые заголовки,
`ETag` наружу). Почему не Garage в dev: его S3 API отвечает только подписанным запросам, а
анонимное чтение — это web-эндпоинт Garage: отдельный порт, маршрутизация по Host и ещё один туннель.

Версия — сборка Protomaps (`20260811`): адрес неизменен, поэтому файлы в R2 кэшируются на год
(`immutable`), а новая карта — новый префикс и новая `MAP_ASSETS_VERSION`.

Для UI (база — `VITE_MAP_ASSETS_URL`; путь от корня привести к абсолютному:
`new URL(base, location.href)`):

- тайлы: `pmtiles://<база>/novi-sad.pmtiles` (протокол `pmtiles` — `maplibregl.addProtocol`);
- глифы: `<база>/fonts/{fontstack}/{range}.pbf`;
- спрайт: `<база>/sprites/v4/light` (тёмная тема — `dark`);
- `maxBounds` — рамка из `provenance.json` (`inputs.bbox`): за ней тайлов нет;
- атрибуция обязательна (ODbL): «© OpenStreetMap» со ссылкой на
  `https://www.openstreetmap.org/copyright` и «Protomaps» — `provenance.json`, поле `attribution`;
- знак вне 9 диапазонов MapLibre рисует системным шрифтом (предупреждение в консоли), тайл не
  ломается;
- пустая `VITE_MAP_ASSETS_URL` или ошибка загрузки — карты нет, остаётся список районов.

CSP собирает `apps/tma/src/app/csp.ts` из той же переменной: с картой — `worker-src 'self' blob:`
(воркеры MapLibre) и origin базы в `connect-src`, если он чужой; `img-src` уже пускает `blob:` и
`data:`. Без карты CSP не меняется. Сборка e2e — всегда без карты (`e2e:build`).

## Новая сборка Protomaps

Архив Protomaps хранит все сборки последней недели и последнюю сборку каждой patch-версии
(`https://build-metadata.protomaps.dev/builds.json`, поле `version`). Закреплять — только такую,
что не пропадёт: последнюю сборку версии, у которой уже есть следующая. Свежая сборка
недельной давности через 7 дней исчезнет, и `make map-assets` на новой машине перестанет работать.

1. `PROTOMAPS_BUILD` в `build.py` → `make map-assets FORCE=1` → карта на стенде.
2. `make map-upload ENV=stage` → Variable `MAP_ASSETS_VERSION` → деплой; то же для prod.
3. Старый префикс `map/<прошлая версия>/` удалить, когда обе среды перешли на новый.

## Лицензии

- Данные: © OpenStreetMap contributors, ODbL 1.0. Тайлы — Produced Work: атрибуция на карте.
- Схема и стиль Protomaps basemap — BSD-3-Clause (`github.com/protomaps/basemaps`).
- Noto Sans — SIL Open Font License 1.1 (`fonts/OFL.txt` рядом с глифами).
- Спрайты — производные `tangrams/icons`, MIT.
