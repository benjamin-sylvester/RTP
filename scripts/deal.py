"""Manual deal lifecycle — kill deals you've reviewed and don't like, or bring one back.
The briefing shows each deal's id, so:
  deal.py --list                 show the active pipeline with ids
  deal.py --kill 23 [reason...]  reject deal #23 -> 'dead' (drops off pipeline + briefing)
  deal.py --reactivate 23        bring a stale/killed deal back -> 'lead'
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _conn import connect
from ingest import freshness


def main():
    a = sys.argv
    with connect(autocommit=False) as conn:
        if "--kill" in a:
            lid = int(a[a.index("--kill") + 1])
            reason = " ".join(a[a.index("--kill") + 2:]) or None
            row = freshness.kill(conn, lid, reason)
            conn.commit()
            print(f"killed #{row[0]} {row[1]}, {row[2]} -> dead" if row
                  else f"#{lid} not found / already dead")
        elif "--reactivate" in a:
            lid = int(a[a.index("--reactivate") + 1])
            row = freshness.reactivate(conn, lid)
            conn.commit()
            print(f"reactivated #{row[0]} {row[1]}, {row[2]} -> lead" if row
                  else f"#{lid} not found / not stale|dead")
        else:  # --list
            print(f"{'id':>4} {'tier':<9}{'status':<13}{'name':<28}market")
            print("-" * 70)
            for r in conn.execute(
                "SELECT d.deal_kind, d.deal_id, d.tier, d.status, d.name, d.market "
                "FROM v_pipeline_deals d").fetchall():
                tag = f"P{r[1]}" if r[0] == "package" else str(r[1])
                print(f"{tag:>4} {str(r[2]):<9}{r[3]:<13}{(r[4] or '?')[:27]:<28}{r[5]}")


if __name__ == "__main__":
    main()
