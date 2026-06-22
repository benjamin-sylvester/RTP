"""Phase 0.5 — apply db/migrations/001_add_packages.sql and group the one
package that already exists in seeded data: 377/379/383 Manchester St (9-unit).
Idempotent."""
from _conn import connect, ROOT

# Packages groupable from parcels ALREADY in the DB. Each links existing
# listings via a WHERE clause; total_units/asking left NULL roll up from members.
PACKAGES = [
    {
        "name": "377-383 Manchester St (9-unit pkg)",
        "market": "Manchester", "state": "NH", "status": "lead",
        "total_units": 9, "asking_price": None,
        "broker_name": "Justin Porter", "broker_email": "justin@portercapitalrei.com",
        "notes": "9-unit package across 3x 3-unit parcels. Ben actively pursuing. "
                 "Package ask TBD (only 377 priced at $499k; RR+P&L requested).",
        "where": "city='Manchester' AND address = ANY(%(addrs)s)",
        "params": {"addrs": ["377 Manchester St", "379 Manchester St", "383 Manchester St"]},
    },
    {
        "name": "Providence portfolio (Federal Hill, 4 props)",
        "market": "Providence", "state": "RI", "status": "comp_only",
        "total_units": None, "asking_price": None,
        "broker_name": "Christian Allen", "broker_email": "callen1992@gmail.com",
        "notes": "Off-market 4-property RI portfolio (triage thread 19d8ce1a...). "
                 "Out of state box -> comp_only. Grouped from existing parcels.",
        "where": "raw_email_id=%(thread)s AND city='Providence'",
        "params": {"thread": "19d8ce1a29a050af"},
    },
]


def main():
    sql = (ROOT / "db" / "migrations" / "001_add_packages.sql").read_text()
    with connect(autocommit=True) as conn:
        conn.execute(sql)
        print("migration 001_add_packages.sql applied.\n")

        # Verify new objects
        has_pkg = conn.execute(
            "SELECT to_regclass('public.packages') IS NOT NULL").fetchone()[0]
        has_col = conn.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name='listings' AND column_name='package_id'"
        ).fetchone()[0]
        has_view = conn.execute(
            "SELECT count(*) FROM pg_views WHERE viewname='v_deals'").fetchone()[0]
        print(f"  [{'OK' if has_pkg else 'MISSING'}] packages table")
        print(f"  [{'OK' if has_col else 'MISSING'}] listings.package_id column")
        print(f"  [{'OK' if has_view else 'MISSING'}] v_deals view\n")

        # Create each package (idempotent by name), then link member parcels.
        for spec in PACKAGES:
            row = conn.execute(
                "SELECT id FROM packages WHERE name=%s", (spec["name"],)).fetchone()
            if row is None:
                row = conn.execute(
                    """
                    INSERT INTO packages
                      (name, market, state, status, total_units, asking_price,
                       broker_name, broker_email, notes)
                    VALUES (%(name)s,%(market)s,%(state)s,%(status)s,%(total_units)s,
                            %(asking_price)s,%(broker_name)s,%(broker_email)s,%(notes)s)
                    RETURNING id
                    """, spec).fetchone()
                print(f"Created package #{row[0]}: {spec['name']}")
            else:
                print(f"Package exists:  #{row[0]}: {spec['name']}")
            pid = row[0]
            n = conn.execute(
                f"UPDATE listings SET package_id=%(pid)s "
                f"WHERE ({spec['where']}) AND package_id IS DISTINCT FROM %(pid)s",
                {**spec["params"], "pid": pid},
            ).rowcount
            print(f"  linked {n} parcel(s).")
        print()

        # Show all packages rolled up via v_deals (effective unit count from members)
        print("=== v_deals: all packages (effective units/ask from members) ===")
        rows = conn.execute(
            """
            SELECT d.deal_id, d.name, d.market, d.state, d.status, d.effective_units,
                   CASE WHEN d.effective_ask IS NULL THEN NULL ELSE d.effective_ask/100 END AS ask_usd,
                   (SELECT count(*) FROM listings l WHERE l.package_id=d.deal_id) AS parcels
            FROM v_deals d
            WHERE d.deal_kind='package'
            ORDER BY d.deal_id
            """).fetchall()
        print(f"{'id':>3}  {'name':<44}{'st':<4}{'status':<11}{'parcels':>8}{'units':>6}{'ask':>13}")
        print("-" * 92)
        for did, name, market, st, status, units, ask, parcels in rows:
            ask_s = f"${ask:,.0f}" if ask is not None else "-"
            print(f"{did:>3}  {(name or '')[:43]:<44}{st:<4}{status:<11}{parcels:>8}"
                  f"{(units if units is not None else '-'):>6}{ask_s:>13}")
        print(f"\n{len(rows)} package(s). Member parcels are excluded from the standalone "
              f"deal list and roll up here on combined unit count.")


if __name__ == "__main__":
    main()
