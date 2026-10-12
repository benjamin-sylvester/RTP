-- Migration 016: core block, part 2. Organizations, people, people_emails (db/DATA_MODEL.md Block 1).
-- Internal people (Ben, Justin, Ren) are rows with role 'internal' (Ben, 10/12/26). Idempotent.

CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE IF NOT EXISTS organizations (
  id              SERIAL PRIMARY KEY,
  name            TEXT NOT NULL,
  kind            TEXT NOT NULL CHECK (kind IN ('brokerage','pm_company','lender','law_firm','capital_partner',
                                              'lp_entity','owner_entity','vendor','insurer','accountant',
                                              'sponsor','other')),
  website         TEXT,
  city            TEXT,
  state           TEXT,
  notes           TEXT,
  source          TEXT,
  source_id       TEXT,
  merged_into_id  INTEGER REFERENCES organizations(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_organizations_name_kind ON organizations (lower(name), kind);
DROP TRIGGER IF EXISTS trg_organizations_touch ON organizations;
CREATE TRIGGER trg_organizations_touch BEFORE UPDATE ON organizations
  FOR EACH ROW EXECUTE FUNCTION rtp_touch_updated_at();

CREATE TABLE IF NOT EXISTS people (
  id                   SERIAL PRIMARY KEY,
  full_name            TEXT NOT NULL,
  first_name           TEXT,
  last_name            TEXT,
  org_id               INTEGER REFERENCES organizations(id),
  title                TEXT,
  roles                TEXT[] NOT NULL DEFAULT '{}'
                         CHECK (roles <@ ARRAY['internal','lp','lp_prospect','capital_partner','broker','owner',
                                               'lender','attorney','vendor','operator_partner','connector',
                                               'pm','accountant','personal']::text[]),
  phone                TEXT,
  linkedin_url         TEXT,
  reconvene_url        TEXT,
  city                 TEXT,
  state                TEXT,
  lp_tier              CHAR(1) CHECK (lp_tier IS NULL OR lp_tier IN ('A','B','C','D')),
  lp_relationship      TEXT,
  lp_indicated_cents   BIGINT,
  lp_next_deal_stage   TEXT,
  owner_score          INTEGER,
  owner_tier           TEXT CHECK (owner_tier IS NULL OR owner_tier IN ('T1','T2','T3','T4')),
  warmth               TEXT CHECK (warmth IS NULL OR warmth IN ('hot','warm','cold','closed')),
  notes                TEXT,
  source               TEXT,
  source_id            TEXT,
  merged_into_id       INTEGER REFERENCES people(id),
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_people_name ON people (lower(full_name));
CREATE INDEX IF NOT EXISTS idx_people_roles ON people USING gin (roles);
CREATE INDEX IF NOT EXISTS idx_people_org ON people (org_id);
DROP TRIGGER IF EXISTS trg_people_touch ON people;
CREATE TRIGGER trg_people_touch BEFORE UPDATE ON people
  FOR EACH ROW EXECUTE FUNCTION rtp_touch_updated_at();

CREATE TABLE IF NOT EXISTS people_emails (
  id          SERIAL PRIMARY KEY,
  person_id   INTEGER NOT NULL REFERENCES people(id),
  email       CITEXT NOT NULL UNIQUE,
  is_primary  BOOLEAN NOT NULL DEFAULT false,
  label       TEXT
);
CREATE INDEX IF NOT EXISTS idx_people_emails_person ON people_emails (person_id);

-- Foreign keys deferred from 015, and broker links on deals
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_properties_owner_org') THEN
    ALTER TABLE properties ADD CONSTRAINT fk_properties_owner_org
      FOREIGN KEY (owner_org_id) REFERENCES organizations(id);
  END IF;
END $$;
ALTER TABLE listings ADD COLUMN IF NOT EXISTS broker_person_id INTEGER REFERENCES people(id);
ALTER TABLE listings ADD COLUMN IF NOT EXISTS broker_org_id INTEGER REFERENCES organizations(id);
ALTER TABLE packages ADD COLUMN IF NOT EXISTS broker_person_id INTEGER REFERENCES people(id);
CREATE INDEX IF NOT EXISTS idx_listings_broker_person ON listings (broker_person_id);

-- Seed: the sponsor and the internal people
INSERT INTO organizations (name, kind, city, state, website, source)
SELECT 'Rising Tide Partners', 'sponsor', 'Boston', 'MA', 'rtprei.com', 'seed 016'
WHERE NOT EXISTS (SELECT 1 FROM organizations WHERE lower(name) = 'rising tide partners' AND kind = 'sponsor');

INSERT INTO people (full_name, first_name, last_name, org_id, title, roles, city, state, source)
SELECT v.full_name, v.first_name, v.last_name,
       (SELECT id FROM organizations WHERE lower(name) = 'rising tide partners' AND kind = 'sponsor'),
       v.title, ARRAY['internal']::text[], v.city, v.state, 'seed 016'
FROM (VALUES
  ('Ben Sylvester', 'Ben', 'Sylvester', 'Founder', 'Boston', 'MA'),
  ('Justin Kanterman', 'Justin', 'Kanterman', 'Partner (Summer St, John St, Baxter)', NULL, NULL),
  ('Ren LaMotte', 'Ren', 'LaMotte', 'John St LP; built the call dashboard', NULL, NULL)
) AS v(full_name, first_name, last_name, title, city, state)
WHERE NOT EXISTS (SELECT 1 FROM people p WHERE lower(p.full_name) = lower(v.full_name));

INSERT INTO people_emails (person_id, email, is_primary, label)
SELECT p.id, v.email, v.is_primary, v.label
FROM (VALUES
  ('Ben Sylvester', 'ben@rtprei.com', true, 'work'),
  ('Ben Sylvester', 'ben.sylvester18@gmail.com', false, 'personal')
) AS v(full_name, email, is_primary, label)
JOIN people p ON lower(p.full_name) = lower(v.full_name)
WHERE NOT EXISTS (SELECT 1 FROM people_emails e WHERE e.email = v.email);
