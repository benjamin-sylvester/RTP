"""Phase 0.4 — verification: haversine radius query + v_pipeline."""
from _conn import connect

MANCH_LAT, MANCH_LON = 42.9956, -71.4548
RADIUS_MI = 10


def usd(cents):
    return f"${cents/100:,.0f}" if cents is not None else "-"


def main():
    with connect() as conn:
        print(f"=== 1) Listings within {RADIUS_MI} mi of Manchester NH "
              f"({MANCH_LAT}, {MANCH_LON}) ===\n")
        rows = conn.execute(
            """
            SELECT address, city, state, units, asking_price, status,
                   ROUND(haversine_miles(%s::numeric, %s::numeric, latitude, longitude), 2) AS miles
            FROM listings
            WHERE latitude IS NOT NULL
              AND haversine_miles(%s::numeric, %s::numeric, latitude, longitude) <= %s
            ORDER BY miles
            """,
            (MANCH_LAT, MANCH_LON, MANCH_LAT, MANCH_LON, RADIUS_MI),
        ).fetchall()
        print(f"{'mi':>5}  {'address':<22}{'city':<13}{'st':<4}{'units':>6}  "
              f"{'asking':>12}  status")
        print("-" * 78)
        for addr, city, st, units, price, status, miles in rows:
            print(f"{float(miles):>5.2f}  {(addr or '')[:21]:<22}{(city or '')[:12]:<13}"
                  f"{st:<4}{(units if units is not None else '-'):>6}  "
                  f"{usd(price):>12}  {status}")
        print(f"\n{len(rows)} rows within {RADIUS_MI} mi.\n")

        print("=== 2) SELECT * FROM v_pipeline ===\n")
        cur = conn.execute("SELECT * FROM v_pipeline ORDER BY city, address")
        cols = [c.name for c in cur.description]
        prows = cur.fetchall()
        show = ["id", "address", "city", "state", "units", "asking_price",
                "price_per_unit", "status", "score", "meets_buy_box"]
        idx = {c: cols.index(c) for c in show}
        print(f"{'id':>3} {'address':<20}{'city':<12}{'st':<4}{'un':>4}"
              f"{'asking':>12}{'ppu':>11}  {'status':<10}{'score':>6} mbb")
        print("-" * 92)
        for r in prows:
            print(f"{r[idx['id']]:>3} {(r[idx['address']] or '')[:19]:<20}"
                  f"{(r[idx['city']] or '')[:11]:<12}{r[idx['state']]:<4}"
                  f"{(r[idx['units']] if r[idx['units']] is not None else '-'):>4}"
                  f"{usd(r[idx['asking_price']]):>12}{usd(r[idx['price_per_unit']]):>11}  "
                  f"{r[idx['status']]:<10}{str(r[idx['score']] if r[idx['score']] is not None else '-'):>6}"
                  f" {r[idx['meets_buy_box']]}")
        print(f"\n{len(prows)} rows in pipeline "
              f"(score/meets_buy_box are NULL — auto_underwriting is Phase 2).")


if __name__ == "__main__":
    main()
