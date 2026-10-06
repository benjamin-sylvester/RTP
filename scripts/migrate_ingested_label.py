"""One-time cutover from the Gmail 'RTP/Ingested' label to the processed_messages table.
  python scripts/migrate_ingested_label.py            import label'd ids into the DB (safe, repeatable)
  python scripts/migrate_ingested_label.py --delete   ALSO delete the RTP/Ingested label from each inbox
                                                      (run only after the new runner is deployed)
Deleting a Gmail label does not touch the messages themselves.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ingest import gmail_client as gc, runner  # noqa: E402

LABEL = "RTP/Ingested"


def main():
    delete = "--delete" in sys.argv
    conn = runner._connect()
    try:
        for acct in gc.accounts():
            svc = gc.service(acct["refresh_token"])
            lid = gc.label_id(svc, LABEL)
            if not lid:
                print(f"[{acct['key']}] no '{LABEL}' label; nothing to import")
                continue
            ids = gc.list_message_ids(svc, LABEL)
            for mid in ids:
                conn.execute(
                    "INSERT INTO processed_messages (account, msg_id, result) "
                    "VALUES (%s,%s,'migrated_from_label') ON CONFLICT DO NOTHING",
                    (acct["key"], mid))
            conn.commit()
            print(f"[{acct['key']}] imported {len(ids)} message id(s) from '{LABEL}'")
            if delete:
                svc.users().labels().delete(userId="me", id=lid).execute()
                print(f"[{acct['key']}] deleted label '{LABEL}'")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
