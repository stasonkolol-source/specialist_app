-- 10_schema.sql — draft normalized schema (write model) of the marketplace.
-- Secondary indexes are created later (14_indexes.sql) so that seeding is fast and index build
-- time/size can be measured separately.
\set ON_ERROR_STOP 1
DROP SCHEMA IF EXISTS mp CASCADE;
CREATE SCHEMA mp;
ALTER DATABASE lab SET search_path = mp, public;
SET search_path = mp, public;

-- ---------- reference data ----------
CREATE TABLE city (
  id            smallint PRIMARY KEY,
  slug          text NOT NULL UNIQUE,
  name          jsonb NOT NULL,                 -- {"ru","sr-Latn","sr-Cyrl","en"}
  center        geography(Point, 4326) NOT NULL,
  gen_radius_m  int NOT NULL,                   -- data generation only
  gen_weight    real NOT NULL                   -- data generation only
);

CREATE TABLE district (
  id        int PRIMARY KEY,
  city_id   smallint NOT NULL REFERENCES city(id),
  slug      text NOT NULL UNIQUE,
  name      jsonb NOT NULL,
  boundary  geometry(MultiPolygon, 4326) NOT NULL,   -- geometry: ST_Covers/ST_Contains + GiST
  center    geography(Point, 4326) NOT NULL
);

CREATE TABLE category (
  id           int PRIMARY KEY,
  parent_id    int REFERENCES category(id),
  path         ltree NOT NULL UNIQUE,            -- repair.electric.electrician
  depth        smallint NOT NULL,
  slug         text NOT NULL UNIQUE,
  name         jsonb NOT NULL,                   -- {"ru","sr-Latn","sr-Cyrl","en"}
  is_synthetic boolean NOT NULL DEFAULT false,   -- padding categories of the lab dataset
  popularity   real NOT NULL DEFAULT 1,          -- data generation weight
  price_base   int                               -- RSD, data generation only
);

-- Alternative i18n layout (compared with JSONB in 06_i18n_collations.sql)
CREATE TABLE category_translation (
  category_id int  NOT NULL REFERENCES category(id) ON DELETE CASCADE,
  locale      text NOT NULL,                     -- ru | sr-Latn | sr-Cyrl | en
  name        text NOT NULL,
  PRIMARY KEY (category_id, locale)
);

-- Taxonomy dictionary for cross-language search / autocomplete: "term -> category"
CREATE TABLE category_term (
  id          int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  category_id int  NOT NULL REFERENCES category(id) ON DELETE CASCADE,
  lang        text NOT NULL,                     -- ru | sr-Latn | sr-Cyrl | en
  term        text NOT NULL,
  kind        text NOT NULL DEFAULT 'synonym',   -- name | synonym
  weight      real NOT NULL DEFAULT 1,
  term_norm   text GENERATED ALWAYS AS (public.search_norm(term)) STORED,
  UNIQUE (category_id, lang, term)
);

CREATE TABLE tag (
  id    smallint PRIMARY KEY,
  slug  text NOT NULL UNIQUE,
  name  jsonb NOT NULL
);

-- ---------- specialists ----------
CREATE TABLE specialist (
  id               uuid PRIMARY KEY DEFAULT uuidv7(),
  display_name     text NOT NULL,
  about            jsonb NOT NULL DEFAULT '{}',   -- user text per language: {"ru": "...", "sr-Latn": "..."}
  primary_lang     text NOT NULL,                 -- ru | sr-Latn | sr-Cyrl | en
  languages        text[] NOT NULL,               -- spoken: {ru,sr,en,uk,...}
  city_id          smallint NOT NULL REFERENCES city(id),
  district_id      int REFERENCES district(id),
  location         geography(Point, 4326) NOT NULL,
  travels          boolean NOT NULL,              -- "выезд" to the client
  travel_radius_m  int,
  rating           numeric(3,2),
  reviews_count    int NOT NULL DEFAULT 0,
  available_on     date,                          -- "available today" == available_on = current_date
  status           text NOT NULL DEFAULT 'active',
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE specialist_category (
  specialist_id uuid NOT NULL REFERENCES specialist(id) ON DELETE CASCADE,
  category_id   int  NOT NULL REFERENCES category(id),
  PRIMARY KEY (specialist_id, category_id)
);

-- price list
CREATE TABLE service (
  id             uuid PRIMARY KEY DEFAULT uuidv7(),
  specialist_id  uuid NOT NULL REFERENCES specialist(id) ON DELETE CASCADE,
  category_id    int  NOT NULL REFERENCES category(id),
  title          text NOT NULL,
  lang           text NOT NULL,
  price_rsd      int  NOT NULL CHECK (price_rsd >= 0),
  price_to_rsd   int,
  unit           text NOT NULL DEFAULT 'job',     -- job | hour | m2 | page | visit
  is_active      boolean NOT NULL DEFAULT true,
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE review (
  id             uuid PRIMARY KEY DEFAULT uuidv7(),
  specialist_id  uuid NOT NULL REFERENCES specialist(id) ON DELETE CASCADE,
  author_id      uuid NOT NULL,
  request_id     uuid,
  rating         smallint NOT NULL CHECK (rating BETWEEN 1 AND 5),
  body           text,
  lang           text,
  created_at     timestamptz NOT NULL DEFAULT now()
);

-- ---------- request board ----------
CREATE TABLE request (
  id              uuid PRIMARY KEY DEFAULT uuidv7(),
  client_id       uuid NOT NULL,
  category_id     int  NOT NULL REFERENCES category(id),
  tag_ids         smallint[] NOT NULL DEFAULT '{}',
  title           text NOT NULL,
  description     text,
  lang            text NOT NULL,
  urgency         smallint NOT NULL,             -- 0 asap, 1 today, 2 this week, 3 flexible
  budget_min_rsd  int,
  budget_max_rsd  int,
  city_id         smallint NOT NULL REFERENCES city(id),
  district_id     int REFERENCES district(id),
  location        geography(Point, 4326) NOT NULL,
  status          text NOT NULL,                 -- open | in_progress | done | cancelled | expired
  created_at      timestamptz NOT NULL,
  expires_at      timestamptz NOT NULL
);

CREATE TABLE response (
  id             uuid PRIMARY KEY DEFAULT uuidv7(),
  request_id     uuid NOT NULL REFERENCES request(id) ON DELETE CASCADE,
  specialist_id  uuid NOT NULL REFERENCES specialist(id) ON DELETE CASCADE,
  message        text,
  price_rsd      int,
  status         text NOT NULL DEFAULT 'sent',  -- sent | accepted | rejected | withdrawn
  created_at     timestamptz NOT NULL
);

-- ---------- subscriptions for new-request notifications ----------
-- Variant A (arrays + GIN): category_ids / district_ids, or center+radius.
CREATE TABLE subscription (
  id              uuid PRIMARY KEY DEFAULT uuidv7(),
  specialist_id   uuid NOT NULL REFERENCES specialist(id) ON DELETE CASCADE,
  category_ids    int[] NOT NULL,                -- as chosen by the specialist (may contain parent categories)
  district_ids    int[],                         -- either districts ...
  center          geography(Point, 4326),        -- ... or a circle
  radius_m        int,
  area            geometry(Polygon, 4326),       -- circle materialized as polygon (indexable point-in-area)
  min_budget_rsd  int,
  is_active       boolean NOT NULL DEFAULT true,
  created_at      timestamptz NOT NULL DEFAULT now(),
  CHECK ((district_ids IS NOT NULL) <> (center IS NOT NULL))
);
-- Variant B (link tables) for the comparison
CREATE TABLE subscription_category (
  subscription_id uuid NOT NULL REFERENCES subscription(id) ON DELETE CASCADE,
  category_id     int  NOT NULL,
  PRIMARY KEY (category_id, subscription_id)
);
CREATE TABLE subscription_district (
  subscription_id uuid NOT NULL REFERENCES subscription(id) ON DELETE CASCADE,
  district_id     int  NOT NULL,
  PRIMARY KEY (district_id, subscription_id)
);
