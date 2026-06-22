"""Phase 0.1 — run db/schema.sql and verify all objects exist."""
import sys
from _conn import connect, ROOT

EXPECTED_TABLES = [
    "listings", "listing_financials", "unit_mix", "auto_underwriting",
    "rent_comps", "listing_history", "broker_format_config",
]
EXPECTED_VIEWS = ["v_pipeline", "v_sale_comps"]
EXPECTED_INDEXES = [
    "idx_listings_latlng", "idx_listings_status", "idx_listings_city_state",
    "idx_listings_units", "idx_listings_ingested", "idx_rentcomps_latlng",
    "idx_rentcomps_market", "idx_unitmix_listing",
]


def main():
    sql = (ROOT / "db" / "schema.sql").read_text()
    with connect(autocommit=True) as conn:
        # psycopg3 executes a multi-statement script in one call (no params).
        conn.execute(sql)
        print("schema.sql executed.\n")

        def names(query):
            return {r[0] for r in conn.execute(query).fetchall()}

        tables = names(
            "SELECT tablename FROM pg_tables WHERE schemaname='public'")
        views = names(
            "SELECT viewname FROM pg_views WHERE schemaname='public'")
        indexes = names(
            "SELECT indexname FROM pg_indexes WHERE schemaname='public'")
        func = conn.execute(
            "SELECT proname FROM pg_proc WHERE proname='haversine_miles'"
        ).fetchall()

        ok = True
        print("TABLES (expect 7):")
        for t in EXPECTED_TABLES:
            mark = "OK" if t in tables else "MISSING"
            ok &= t in tables
            print(f"  [{mark}] {t}")

        print("\nVIEWS (expect 2):")
        for v in EXPECTED_VIEWS:
            mark = "OK" if v in views else "MISSING"
            ok &= v in views
            print(f"  [{mark}] {v}")

        print("\nINDEXES (expect 8 explicit):")
        for i in EXPECTED_INDEXES:
            mark = "OK" if i in indexes else "MISSING"
            ok &= i in indexes
            print(f"  [{mark}] {i}")

        print("\nFUNCTION:")
        fmark = "OK" if func else "MISSING"
        ok &= bool(func)
        print(f"  [{fmark}] haversine_miles()")

        # sanity: haversine Manchester NH -> Nashua NH ~ 17.7 mi
        d = conn.execute(
            "SELECT haversine_miles(42.9956, -71.4548, 42.7654, -71.4676)"
        ).fetchone()[0]
        print(f"\n  haversine_miles(Manchester, Nashua) = {float(d):.2f} mi "
              f"(expect ~16-18)")

        print("\nRESULT:", "ALL OBJECTS PRESENT" if ok else "VERIFICATION FAILED")
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
