-- Migration 004: tiny key/value table for app state (e.g. briefing last_briefed_at).
-- Idempotent.
CREATE TABLE IF NOT EXISTS system_meta (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
