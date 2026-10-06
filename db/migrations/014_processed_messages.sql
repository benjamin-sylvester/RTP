-- Migration 014: track processed Gmail messages in the DB instead of a Gmail label.
-- Ben does not want ingestion labeling anything in either inbox (Gmail is read-only
-- for the ingester). One row per (inbox, message id). Idempotent.
CREATE TABLE IF NOT EXISTS processed_messages (
    account      TEXT NOT NULL,          -- gmail_client.accounts() key: personal | rtp
    msg_id       TEXT NOT NULL,          -- Gmail message id
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    result       TEXT,                   -- parse path + actions, 'baseline', 'error:...'
    PRIMARY KEY (account, msg_id)
);
