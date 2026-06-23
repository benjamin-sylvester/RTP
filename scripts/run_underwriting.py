"""Phase 2 step 1-3: compute buy-box flags + metrics + score/tier/confidence for
every deal in v_deals (package-aware) and write to auto_underwriting. No AI here."""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _conn import connect
from ingest import underwrite


def load_deals(conn):
    rows = conn.execute(
        "SELECT deal_kind, deal_id, name, market, state, status, "
        "effective_units, effective_ask FROM v_deals").fetchall()
    deals = []
    for kind, did, name, market, state, status, units, ask in rows:
        yb = cls = None
        if kind == "listing":
            r = conn.execute(
                "SELECT year_built, property_class FROM listings WHERE id=%s", (did,)
            ).fetchone()
            yb, cls = r if r else (None, None)
        deals.append({"deal_kind": kind, "deal_id": did, "name": name,
                      "market": market, "state": state, "status": status,
                      "effective_units": units, "effective_ask_cents": ask,
                      "year_built": yb, "property_class": cls})
    return deals


def main():
    with connect(autocommit=False) as conn:
        deals = load_deals(conn)
        tiers = {"Priority": 0, "Watch": 0, "Pass": 0}
        for d in deals:
            au = underwrite.compute(conn, d)
            underwrite.write(conn, d, au)
            tiers[au["tier"]] += 1
        conn.commit()
        print(f"Scored {len(deals)} deals  ->  "
              f"Priority {tiers['Priority']}, Watch {tiers['Watch']}, Pass {tiers['Pass']}")
        print("\nPipeline (v_pipeline_deals), ranked:")
        print(f"{'tier':<9}{'score':>5} {'conf':<7}{'mbb':<5}{'units':>5}{'ask':>12}  name")
        print("-" * 92)
        for r in conn.execute(
            "SELECT tier, score, score_confidence, meets_buy_box, effective_units, "
            "effective_ask, name, market FROM v_pipeline_deals").fetchall():
            tier, score, conf, mbb, u, ask, name, mkt = r
            ask_s = f"${ask/100:,.0f}" if ask else "-"
            print(f"{str(tier):<9}{str(score if score is not None else '-'):>5} "
                  f"{str(conf or '-'):<7}{str(mbb):<5}{str(u or '-'):>5}{ask_s:>12}  "
                  f"{(name or '')[:30]}, {mkt}")


if __name__ == "__main__":
    main()
