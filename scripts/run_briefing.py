"""Daily briefing runner.
  run_briefing.py --dry            render to briefing_preview.html, no send, no timestamp
  run_briefing.py --send [--to X]  send to DISPATCH_EMAIL (or --to), advance last_briefed_at
"""
import sys
import pathlib
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _conn import connect
from ingest import gmail_client as gc, briefing

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    send = "--send" in sys.argv
    to = None
    if "--to" in sys.argv:
        to = sys.argv[sys.argv.index("--to") + 1]
    # --since YYYY-MM-DD: display-only window override (dry-run; never touches the
    # stored last_briefed_at). Useful to preview the full active pipeline.
    since_override = (datetime.fromisoformat(sys.argv[sys.argv.index("--since") + 1])
                      if "--since" in sys.argv else None)
    preview = None if send else str(ROOT / "briefing_preview.html")
    svc = gc.service() if send else None

    with connect(autocommit=False) as conn:
        res = briefing.run(conn, svc=svc, send=send, to=to, preview_path=preview,
                           since_override=since_override)
        d = res["data"]
        print(f"since: {res['since']:%Y-%m-%d %H:%M}")
        print(f"subject: {res['subject']}")
        print(f"  new leads: {len(d['new_leads'])}, price cuts: {len(d['price_cuts'])}, "
              f"pipeline changes: {len(d['pipeline_changes'])}, "
              f"market moves: {len(d['market_changes'])}, gone quiet: {len(d['gone_quiet'])}, "
              f"enrichments: {d['enrich_n']}, needs_review: {len(d['needs_review'])}")
        if send:
            print(f"SENT to {to or 'DISPATCH_EMAIL'} (id={res['sent_id']}); last_briefed_at advanced.")
        else:
            print(f"DRY-RUN rendered to {preview} (no send, timestamp unchanged).")


if __name__ == "__main__":
    main()
