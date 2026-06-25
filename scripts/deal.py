"""Manual deal lifecycle from the CLI (the dashboard is the main UI now).
  deal.py --list                        active pipeline with ids
  deal.py --status listing 23 passed [reason]   set any status (STATUS_MODEL set)
  deal.py --kill 23 [reason]            shortcut: -> passed (chose not to pursue)
  deal.py --reactivate listing 23       -> lead
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _conn import connect
from ingest import freshness


def main():
    a = sys.argv
    with connect(autocommit=False) as conn:
        if "--status" in a:
            i = a.index("--status")
            kind, did, status = a[i + 1], int(a[i + 2]), a[i + 3]
            reason = " ".join(a[i + 4:]) or None
            r = freshness.set_status(conn, kind, did, status, reason)
            conn.commit()
            print(f"{kind} #{did}: {r['old']} -> {r['new']} ({r['name']})" if r else "not found")
        elif "--kill" in a:
            did = int(a[a.index("--kill") + 1]); reason = " ".join(a[a.index("--kill") + 2:]) or None
            r = freshness.kill(conn, did, reason); conn.commit()
            print(f"#{did} {r['name']} -> passed" if r else "not found")
        elif "--reactivate" in a:
            i = a.index("--reactivate")
            kind, did = (a[i + 1], int(a[i + 2])) if not a[i + 1].isdigit() else ("listing", int(a[i + 1]))
            r = freshness.reactivate(conn, did, kind); conn.commit()
            print(f"{kind} #{did} {r['name']} -> lead" if r else "not found / not eligible")
        else:
            print(f"{'id':>4} {'tier':<9}{'status':<15}{'name':<28}market")
            print("-" * 72)
            for r in conn.execute(
                "SELECT d.deal_kind, d.deal_id, d.tier, d.status, d.name, d.market "
                "FROM v_pipeline_deals d").fetchall():
                tag = f"P{r[1]}" if r[0] == "package" else str(r[1])
                print(f"{tag:>4} {str(r[2]):<9}{r[3]:<15}{(r[4] or '?')[:27]:<28}{r[5]}")


if __name__ == "__main__":
    main()
