"""CLI entry for one ingestion pass (invoked by the cron or by hand).
  run_ingest.py                 process new mail, commit, label  (the cron command)
  run_ingest.py --dry           process but roll back, no labels  (preview)
  run_ingest.py --label-baseline label the already-backfilled window, no processing
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ingest import runner

if __name__ == "__main__":
    if "--label-baseline" in sys.argv:
        runner.label_baseline()
    else:
        runner.run_once(commit="--dry" not in sys.argv,
                        do_label="--dry" not in sys.argv)
