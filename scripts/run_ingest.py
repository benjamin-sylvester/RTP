"""CLI entry for one ingestion pass (invoked by the cron or by hand).
  run_ingest.py              process new mail across all inboxes, commit, mark processed (the cron command)
  run_ingest.py --dry        process but roll back; nothing marked processed (preview)
  run_ingest.py --baseline   mark the current scan window processed WITHOUT parsing (skip a backlog)
Processed tracking is the processed_messages table (migration 014); Gmail is never labeled.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ingest import runner

if __name__ == "__main__":
    if "--baseline" in sys.argv:
        runner.baseline()
    else:
        runner.run_once(commit="--dry" not in sys.argv)
