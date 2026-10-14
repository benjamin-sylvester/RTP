"""Queue messages that failed on an Anthropic credit / API error for re-ingestion.
The ingest marks a failed message as processed so a poison message is never retried forever;
when the failure was on OUR side (no API credits), those messages must be retried. This deletes
their processed_messages rows so the next 15-minute cycle picks them up again (they are still
inside the 30-day scan window).
  python scripts/retry_failed_messages.py [--since 2026-10-07] [--commit]
"""
import sys

from _conn import connect


def main():
    since = sys.argv[sys.argv.index("--since") + 1] if "--since" in sys.argv else "2026-10-01"
    c = connect(autocommit=False)
    rows = c.execute("SELECT account, count(*) FROM processed_messages WHERE result LIKE 'error:BadRequestError%%' "
                     "AND processed_at >= %s GROUP BY 1", (since,)).fetchall()
    print("to retry:", rows)
    n = c.execute("DELETE FROM processed_messages WHERE result LIKE 'error:BadRequestError%%' AND processed_at >= %s", (since,)).rowcount
    if "--commit" in sys.argv:
        c.commit(); print(f"COMMITTED: {n} messages will be re-ingested on the next cycle")
    else:
        c.rollback(); print(f"DRY-RUN: {n} messages would be queued; add --commit")


if __name__ == "__main__":
    main()
