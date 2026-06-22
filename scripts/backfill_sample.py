"""Phase 1 GATE — dry-run backfill over a recent window so Ben can verify extraction
+ routing BEFORE the cron writes anything. Processes every Deal Flow message in the
window through the real pipeline + dedup.upsert inside ONE transaction, prints what
WOULD happen, then ROLLS BACK (pass --commit to persist).

Usage: backfill_sample.py [YYYY/MM/DD] [--commit]   (default window: last 14 days)
"""
import sys
import pathlib
import datetime as dt

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _conn import connect
from ingest import gmail_client as gc, pipeline, dedup
import requests

COMMIT = "--commit" in sys.argv
args = [a for a in sys.argv[1:] if not a.startswith("--")]
after = args[0] if args else (dt.date(2026, 6, 22) - dt.timedelta(days=14)).strftime("%Y/%m/%d")


def usd(cents):
    return f"${cents/100:,.0f}" if cents is not None else "-"


def main():
    svc = gc.service()
    session = requests.Session()
    # oldest-first so a listing's newest price ends up current and price changes
    # log in chronological order to listing_history.
    ids = list(reversed(gc.list_message_ids(svc, "Deal Flow", after=after)))
    print(f"Window: after {after}  |  {len(ids)} messages (oldest-first)\n")

    rows, n_listings, actions = [], 0, {"enriched": 0, "inserted": 0}
    with connect(autocommit=False) as conn:
        for mid in ids:
            msg = gc.get_message(svc, mid)
            bkey, path, cands = pipeline.extract_candidates(svc, msg, session)
            tag = bkey or "(unmatched)"
            if not cands:
                rows.append((tag, path or "-", msg["subject"][:30], "-", "", "no listing", ""))
                continue
            for c in cands:
                n_listings += 1
                res = dedup.upsert(conn, c, source=pipeline.source_for(path),
                                   raw_email_id=c.get("_thread_id"), session=session)
                actions[res["action"]] = actions.get(res["action"], 0) + 1
                loc = f"{(c.get('address') or '?')[:20]}, {c.get('city') or '?'} {c.get('state') or ''}"
                units = c.get("units")
                if res["action"] == "enriched":
                    detail = f"#{res['listing_id']} via {res['tier']} (+{len(res['changed'])} fields)"
                elif res["action"] == "linked_package":
                    detail = f"pkg #{res['package_id']} via {res['matched_on']} (+{len(res['changed'])})"
                else:
                    detail = f"#{res['listing_id']} -> {res['status']}"
                rows.append((tag, path, loc[:30], str(units) if units is not None else "-",
                             usd(dedup._cents(c.get("asking_price"))),
                             res["action"], detail))
        # report
        print(f"{'broker':<13}{'path':<11}{'location':<31}{'un':>4}{'ask':>12}  {'action':<9}{'detail'}")
        print("-" * 120)
        for tag, path, loc, units, ask, action, detail in rows:
            print(f"{tag:<13}{(path or '-'):<11}{loc:<31}{units:>4}{ask:>12}  {action:<9}{detail}")
        print(f"\n{len(ids)} messages -> {n_listings} listing(s): "
              f"{actions.get('inserted',0)} new, {actions.get('enriched',0)} enriched, "
              f"{actions.get('linked_package',0)} pkg-linked.")

        if COMMIT:
            conn.commit(); print("COMMITTED to database.")
        else:
            conn.rollback(); print("ROLLED BACK (dry-run). Re-run with --commit to persist.")


if __name__ == "__main__":
    main()
