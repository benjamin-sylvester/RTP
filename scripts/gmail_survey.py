"""Phase 1 recon — survey the Deal Flow corpus to design the classifier/parsers.
Reports per-sender counts, body type (html/plain), attachment mime mix, and which
broker_format_config key each sender maps to. Read-only."""
import sys
from collections import Counter, defaultdict

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from ingest import gmail_client as gc

LABEL = "Deal Flow"


def main():
    after = sys.argv[1] if len(sys.argv) > 1 else None  # 'YYYY/MM/DD'
    svc = gc.service()
    ids = gc.list_message_ids(svc, LABEL, after=after)
    print(f"{len(ids)} messages under '{LABEL}'"
          f"{(' after '+after) if after else ''}.\n")

    by_sender = Counter()
    broker_of = {}
    body_types = Counter()
    att_mimes = Counter()
    unmatched = Counter()
    examples = defaultdict(list)

    for i, mid in enumerate(ids):
        m = gc.get_message(svc, mid)
        sender = m["from_email"]
        by_sender[sender] += 1
        bkey = gc.match_broker(sender)
        broker_of[sender] = bkey or "(unmatched)"
        if bkey is None:
            unmatched[sender] += 1
        has_html = bool(m["html"].strip())
        has_plain = bool(m["plain"].strip())
        body_types["html" if has_html else ("plain" if has_plain else "empty")] += 1
        for a in m["attachments"]:
            att_mimes[a["mime"]] += 1
        if len(examples[broker_of[sender]]) < 2:
            examples[broker_of[sender]].append(
                f"{m['subject'][:60]!r} | atts={[a['filename'] for a in m['attachments']]}")

    print("=== Senders (mapped to broker_format_config) ===")
    print(f"{'count':>5}  {'broker_key':<16}{'from'}")
    print("-" * 70)
    for sender, n in by_sender.most_common():
        print(f"{n:>5}  {broker_of[sender]:<16}{sender}")

    print("\n=== Body types ===")
    for t, n in body_types.most_common():
        print(f"  {t:<7} {n}")

    print("\n=== Attachment mime types ===")
    if att_mimes:
        for mime, n in att_mimes.most_common():
            print(f"  {n:>4}  {mime}")
    else:
        print("  (none)")

    if unmatched:
        print("\n=== UNMATCHED senders (not in broker_format_config) ===")
        for sender, n in unmatched.most_common():
            print(f"  {n:>4}  {sender}")

    print("\n=== Example subjects per broker_key ===")
    for bkey, exs in examples.items():
        print(f"  [{bkey}]")
        for e in exs:
            print(f"      {e}")


if __name__ == "__main__":
    main()
