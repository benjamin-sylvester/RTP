"""Phase 3 steps 1-2 — load HUD FMR baseline into rent_comps (source 'hud') and wire
unit_mix.market_rent = median of MARKET-source comps (hud/zillow/costar, NEVER
rent_roll) for that market + unit type. Recompute rent_delta_pct (in-place vs market)."""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _conn import connect
from ingest import hud_fmr
from ingest.underwrite import market_rent, beds_from_type


def main():
    with connect(autocommit=False) as conn:
        n = hud_fmr.load(conn)
        print(f"Loaded {n} HUD FMR rent_comps (source 'hud', FY{hud_fmr.FMR_YEAR}).")

        # wire unit_mix.market_rent from market-source comps only
        rows = conn.execute(
            "SELECT um.id, l.city, um.unit_type, um.avg_rent "
            "FROM unit_mix um JOIN listings l ON l.id = um.listing_id").fetchall()
        wired = 0
        for umid, city, unit_type, avg_rent in rows:
            mr = market_rent(conn, city, beds_from_type(unit_type))
            if mr is None:
                continue
            delta = ((avg_rent - mr) / mr) if avg_rent else None
            conn.execute("UPDATE unit_mix SET market_rent=%s, rent_delta_pct=%s WHERE id=%s",
                         (round(mr), delta, umid))
            wired += 1
        print(f"Wired market_rent on {wired}/{len(rows)} unit_mix rows.\n")

        print("Market-rent baseline (HUD medians by market):")
        for r in conn.execute(
            "SELECT market, unit_type, rent FROM rent_comps WHERE source='hud' "
            "AND unit_type IN ('1BR','2BR','3BR') AND market IN "
            "('Manchester','Nashua','Dover','Pittsfield') ORDER BY market, beds").fetchall():
            print(f"  {r[0]:<12}{r[1]:<5} ${r[2]:,}/mo (market)")
        conn.commit()


if __name__ == "__main__":
    main()
