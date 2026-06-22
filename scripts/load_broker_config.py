"""Phase 0.2 — load config/broker_format_config.yaml into broker_format_config.
Idempotent upsert keyed on broker_key. field_map holds the column mapping
(empty {} for AI-parsed senders); routing metadata is preserved in notes."""
import json
import yaml
from _conn import connect, ROOT


def main():
    cfg = yaml.safe_load((ROOT / "config" / "broker_format_config.yaml").read_text())
    sources = cfg["sources"]

    rows = []
    for key, s in sources.items():
        field_map = s.get("field_map", {})
        meta = {
            "format": s.get("format"),
            "parse": s.get("parse"),
            "from": s.get("from"),
            "via": s.get("via"),
        }
        notes_parts = [f"{k}={v}" for k, v in meta.items() if v]
        if s.get("notes"):
            notes_parts.append(f"note={s['notes']}")
        notes = "; ".join(notes_parts)
        rows.append((key, s.get("display_name"), json.dumps(field_map), notes))

    with connect(autocommit=True) as conn:
        for key, display, fmap, notes in rows:
            conn.execute(
                """
                INSERT INTO broker_format_config (broker_key, display_name, field_map, notes)
                VALUES (%s, %s, %s::jsonb, %s)
                ON CONFLICT (broker_key) DO UPDATE
                  SET display_name = EXCLUDED.display_name,
                      field_map    = EXCLUDED.field_map,
                      notes        = EXCLUDED.notes
                """,
                (key, display, fmap, notes),
            )
        print(f"Upserted {len(rows)} broker configs.\n")
        print(f"{'broker_key':<16}{'display_name':<42}{'map cols':<9}notes")
        print("-" * 110)
        for key, display, fmap, notes in conn.execute(
            "SELECT broker_key, display_name, "
            "(SELECT count(*) FROM jsonb_object_keys(field_map)), notes "
            "FROM broker_format_config ORDER BY broker_key"
        ).fetchall():
            print(f"{key:<16}{(display or ''):<42}{fmap:<9}{notes}")


if __name__ == "__main__":
    main()
