"""One-time backfill: lift seeded deals' in-place financials + unit mix out of
raw_data into listing_financials and unit_mix, so every deal reads from the same
tables (no raw_data special-casing in the API/frontend). Fills NULLs only — never
overwrites real enriched data. Idempotent. Money -> cents."""
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _conn import connect

COMMIT = "--commit" in sys.argv
_MIX = re.compile(r"(\d+)\s*x\s*(\d+)\s*BR", re.I)


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    fin_n = um_n = 0
    with connect(autocommit=False) as conn:
        rows = conn.execute(
            "SELECT id, raw_data->>'in_place_gsi', raw_data->>'gross_rent_ann', "
            "raw_data->>'gross_rent_mo', raw_data->>'listed_cap_rate', raw_data->>'unit_mix' "
            "FROM listings WHERE raw_data IS NOT NULL").fetchall()
        for lid, gsi, ann, mo, cap, mix in rows:
            gsi_usd = _f(gsi) or _f(ann) or (_f(mo) * 12 if _f(mo) else None)
            cap_r = _f(cap)

            # financials: create/fill nulls only
            if gsi_usd or cap_r:
                ex = conn.execute(
                    "SELECT gross_revenue, cap_rate FROM listing_financials WHERE listing_id=%s",
                    (lid,)).fetchone()
                if ex is None:
                    conn.execute("INSERT INTO listing_financials (listing_id) VALUES (%s)", (lid,))
                    ex = (None, None)
                sets, vals = [], []
                if gsi_usd and ex[0] is None:
                    sets.append("gross_revenue=%s"); vals.append(round(gsi_usd * 100))
                if cap_r and ex[1] is None:
                    sets.append("cap_rate=%s"); vals.append(cap_r)
                if sets:
                    sets += ["data_source=COALESCE(data_source,'broker')",
                             "confidence=COALESCE(confidence,'low')"]
                    conn.execute(f"UPDATE listing_financials SET {', '.join(sets)} "
                                 f"WHERE listing_id=%s", (*vals, lid))
                    fin_n += 1

            # unit_mix: only if none exist and the string parses to "Nx MBR"
            if mix:
                has = conn.execute("SELECT count(*) FROM unit_mix WHERE listing_id=%s",
                                   (lid,)).fetchone()[0]
                if has == 0:
                    for cnt, beds in _MIX.findall(mix):
                        conn.execute(
                            "INSERT INTO unit_mix (listing_id, unit_type, count) VALUES (%s,%s,%s)",
                            (lid, f"{beds}BR", int(cnt)))
                        um_n += 1
        print(f"financials filled on {fin_n} listing(s); unit_mix rows inserted: {um_n}")
        if COMMIT:
            conn.commit(); print("COMMITTED.")
        else:
            conn.rollback(); print("(dry-run; --commit to apply)")


if __name__ == "__main__":
    main()
