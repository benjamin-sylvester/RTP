"""The 15-minute ingestion cron (in-process scheduler).
Run as a long-lived worker (locally, or a Railway 'worker' service):
    .venv/Scripts/python.exe scripts/scheduler.py

Alternatively, on Railway use a native cron that runs `python scripts/run_ingest.py`
every INGEST_INTERVAL_MINUTES instead of this blocking process.
"""
import os
import sys
import pathlib
import traceback
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from apscheduler.schedulers.blocking import BlockingScheduler

from ingest import runner
from ingest.gmail_client import _load_env

_load_env()
INTERVAL = int(os.environ.get("INGEST_INTERVAL_MINUTES", "15"))


def job():
    try:
        runner.run_once()
    except Exception:
        print("[ingest] run failed:\n" + traceback.format_exc())


def main():
    sched = BlockingScheduler(timezone="America/New_York")
    sched.add_job(job, "interval", minutes=INTERVAL, next_run_time=datetime.now())
    print(f"[ingest] scheduler started — every {INTERVAL} min. Ctrl-C to stop.")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        print("[ingest] scheduler stopped.")


if __name__ == "__main__":
    main()
