"""Reconciliation for migration 015 (properties). Run against sandbox or production:
  python scripts/reconcile_015.py [--sandbox]
"""
import os
import sys

import psycopg
from _conn import connect, load_env


def main():
    if "--sandbox" in sys.argv:
        load_env()
        c = psycopg.connect(os.environ["SANDBOX_DATABASE_URL"])
    else:
        c = connect()
    q = lambda s: c.execute(s).fetchall()
    print("properties (total, owned):", q("SELECT count(*), count(*) FILTER (WHERE rtp_relationship='owned') FROM properties"))
    print("listings total / with property / without:",
          q("SELECT count(*), count(property_id), count(*)-count(property_id) FROM listings WHERE merged_into_id IS NULL"))
    print("without property (sample):")
    for r in q("SELECT id, address, city, state FROM listings WHERE property_id IS NULL AND merged_into_id IS NULL ORDER BY id LIMIT 15"):
        print("   ", r)
    print("keys sample:")
    for r in q("SELECT address, city, address_key FROM properties ORDER BY random() LIMIT 8"):
        print("   ", r)
    print("dup candidates:")
    for r in q("SELECT address_a, address_b, city FROM v_duplicate_property_candidates LIMIT 15"):
        print("   ", r)
    print("owned:")
    for r in q("SELECT id, address, city, units, drive_folder_id FROM properties WHERE rtp_relationship='owned'"):
        print("   ", r)
    print("properties with several listings:")
    for r in q("SELECT p.address, p.city, count(l.id) FROM properties p JOIN listings l ON l.property_id=p.id "
               "GROUP BY 1,2 HAVING count(*)>1 ORDER BY 3 DESC LIMIT 8"):
        print("   ", r)


if __name__ == "__main__":
    main()
