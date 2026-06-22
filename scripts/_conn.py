"""Shared DB connection helper for Phase 0 scripts.
Loads DATABASE_URL from .env (no extra deps; simple parser)."""
import os
import pathlib
import psycopg

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_env():
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def connect(autocommit=True):
    load_env()
    url = os.environ["DATABASE_URL"]
    return psycopg.connect(url, autocommit=autocommit)
