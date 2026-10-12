-- Migration 017: core block, part 3. Events and pointers: interactions, action_items, documents,
-- drive_map, offers, uw_model_versions (db/DATA_MODEL.md Blocks 1 and 2). Idempotent.
-- interactions is append-only (trigger). offers can be updated (response fields) but never deleted.

CREATE OR REPLACE FUNCTION rtp_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION '% is append-only (no % allowed)', TG_TABLE_NAME, TG_OP; END $$;
CREATE OR REPLACE FUNCTION rtp_no_delete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION '% rows are never deleted; use a status flag', TG_TABLE_NAME; END $$;

CREATE TABLE IF NOT EXISTS interactions (
  id            SERIAL PRIMARY KEY,
  person_id     INTEGER REFERENCES people(id),
  org_id        INTEGER REFERENCES organizations(id),
  listing_id    INTEGER REFERENCES listings(id),
  package_id    INTEGER REFERENCES packages(id),
  property_id   INTEGER REFERENCES properties(id),
  entity_id     INTEGER,                      -- FK added in 019
  channel       TEXT NOT NULL CHECK (channel IN ('email','call','meeting','linkedin','reconvene','text','in_person','other')),
  direction     TEXT NOT NULL CHECK (direction IN ('inbound','outbound','mutual')),
  occurred_at   TIMESTAMPTZ NOT NULL,
  summary       TEXT NOT NULL,
  by_person_id  INTEGER REFERENCES people(id), -- internal person who spoke or logged
  source        TEXT,
  source_id     TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (person_id IS NOT NULL OR org_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_interactions_person_time ON interactions (person_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_interactions_listing ON interactions (listing_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_interactions_source ON interactions (source, source_id, person_id)
  WHERE source IS NOT NULL AND source_id IS NOT NULL;
DROP TRIGGER IF EXISTS trg_interactions_append_only ON interactions;
CREATE TRIGGER trg_interactions_append_only BEFORE UPDATE OR DELETE ON interactions
  FOR EACH ROW EXECUTE FUNCTION rtp_append_only();

CREATE TABLE IF NOT EXISTS action_items (
  id               SERIAL PRIMARY KEY,
  title            TEXT NOT NULL,
  details          TEXT,
  owner_person_id  INTEGER REFERENCES people(id),
  due_on           DATE,
  status           TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','waiting','done','dropped')),
  person_id        INTEGER REFERENCES people(id),
  org_id           INTEGER REFERENCES organizations(id),
  listing_id       INTEGER REFERENCES listings(id),
  package_id       INTEGER REFERENCES packages(id),
  property_id      INTEGER REFERENCES properties(id),
  entity_id        INTEGER,                   -- FK added in 019
  source           TEXT,
  source_id        TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_action_items_open ON action_items (status, due_on);
DROP TRIGGER IF EXISTS trg_action_items_touch ON action_items;
CREATE TRIGGER trg_action_items_touch BEFORE UPDATE ON action_items
  FOR EACH ROW EXECUTE FUNCTION rtp_touch_updated_at();
DROP TRIGGER IF EXISTS trg_action_items_no_delete ON action_items;
CREATE TRIGGER trg_action_items_no_delete BEFORE DELETE ON action_items
  FOR EACH ROW EXECUTE FUNCTION rtp_no_delete();

CREATE TABLE IF NOT EXISTS documents (
  id             SERIAL PRIMARY KEY,
  drive_file_id  TEXT UNIQUE,
  drive_url      TEXT,
  title          TEXT NOT NULL,
  doc_type       TEXT NOT NULL CHECK (doc_type IN ('om','rent_roll','t12','pnl','balance_sheet','lease','psa','loi',
                                                   'model','boe','investor_report','k1','insurance','loan_doc',
                                                   'tax_card','deed','photo','pm_export','survey','inspection',
                                                   'operating_agreement','subscription','other')),
  listing_id     INTEGER REFERENCES listings(id),
  package_id     INTEGER REFERENCES packages(id),
  property_id    INTEGER REFERENCES properties(id),
  entity_id      INTEGER,                     -- FK added in 019
  person_id      INTEGER REFERENCES people(id),
  version        TEXT,
  doc_date       DATE,
  mime           TEXT,
  size_bytes     BIGINT,
  sha256         TEXT,
  notes          TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_documents_listing ON documents (listing_id);
CREATE INDEX IF NOT EXISTS idx_documents_property ON documents (property_id);
CREATE INDEX IF NOT EXISTS idx_documents_type ON documents (doc_type);

CREATE TABLE IF NOT EXISTS drive_map (
  id               SERIAL PRIMARY KEY,
  entity_kind      TEXT NOT NULL CHECK (entity_kind IN ('property','listing','package','entity','firm')),
  entity_id        INTEGER,
  purpose          TEXT NOT NULL,
  drive_folder_id  TEXT NOT NULL,
  path             TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_drive_map ON drive_map (entity_kind, COALESCE(entity_id, 0), purpose);

CREATE TABLE IF NOT EXISTS offers (
  id                 SERIAL PRIMARY KEY,
  listing_id         INTEGER REFERENCES listings(id),
  package_id         INTEGER REFERENCES packages(id),
  offer_type         TEXT NOT NULL CHECK (offer_type IN ('indicative','loi','loi_revised','counter_received',
                                                         'psa_draft','psa_executed')),
  direction          TEXT NOT NULL CHECK (direction IN ('sent','received')),
  offer_date         DATE NOT NULL,
  price_cents        BIGINT,
  terms              JSONB,
  document_id        INTEGER REFERENCES documents(id),
  sent_to_person_id  INTEGER REFERENCES people(id),
  response           TEXT NOT NULL DEFAULT 'pending'
                       CHECK (response IN ('pending','accepted','declined','countered','expired','withdrawn')),
  response_date      DATE,
  response_notes     TEXT,
  notes              TEXT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK ((listing_id IS NOT NULL)::int + (package_id IS NOT NULL)::int = 1)
);
CREATE INDEX IF NOT EXISTS idx_offers_listing ON offers (listing_id);
CREATE INDEX IF NOT EXISTS idx_offers_package ON offers (package_id);
DROP TRIGGER IF EXISTS trg_offers_touch ON offers;
CREATE TRIGGER trg_offers_touch BEFORE UPDATE ON offers
  FOR EACH ROW EXECUTE FUNCTION rtp_touch_updated_at();
DROP TRIGGER IF EXISTS trg_offers_no_delete ON offers;
CREATE TRIGGER trg_offers_no_delete BEFORE DELETE ON offers
  FOR EACH ROW EXECUTE FUNCTION rtp_no_delete();

CREATE TABLE IF NOT EXISTS uw_model_versions (
  id              SERIAL PRIMARY KEY,
  listing_id      INTEGER REFERENCES listings(id),
  package_id      INTEGER REFERENCES packages(id),
  drive_file_id   TEXT NOT NULL,
  file_name       TEXT NOT NULL,
  version_label   TEXT,
  modified_at     TIMESTAMPTZ NOT NULL,
  synced_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  price_cents     BIGINT,
  cap_in          NUMERIC(8,6),
  cap_stabilized  NUMERIC(8,6),
  irr             NUMERIC(8,6),
  moic            NUMERIC(8,4),
  metrics         JSONB,
  CHECK ((listing_id IS NOT NULL)::int + (package_id IS NOT NULL)::int = 1)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_uw_model_versions ON uw_model_versions (drive_file_id, modified_at);
