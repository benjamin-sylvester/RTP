"""DB layer for the dashboard API — reuses the same .env DATABASE_URL and returns
JSON-safe dict rows (Decimal -> float, date/datetime -> ISO)."""
import datetime
import decimal
import os

import psycopg
from psycopg.rows import dict_row

from ingest.gmail_client import _load_env  # reuse the existing .env loader


def connect():
    _load_env()
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


def _jsonable(v):
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    return v


def _clean(row):
    return {k: _jsonable(v) for k, v in row.items()}


def query(sql, params=None):
    with connect() as conn:
        return [_clean(r) for r in conn.execute(sql, params or ()).fetchall()]


def one(sql, params=None):
    with connect() as conn:
        r = conn.execute(sql, params or ()).fetchone()
        return _clean(r) if r else None
