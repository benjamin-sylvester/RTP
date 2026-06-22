"""Phase 1 validation — run the AI parser on real Deal Flow emails and print
extracted listings, so accuracy can be eyeballed against the source.
Usage: test_parse.py <broker_key> [n]   e.g. test_parse.py porter 1
"""
import json
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ingest import gmail_client as gc
from ingest import parsers

LABEL = "Deal Flow"


def main():
    want = sys.argv[1] if len(sys.argv) > 1 else "porter"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    svc = gc.service()
    ids = gc.list_message_ids(svc, LABEL)

    done = 0
    for mid in ids:
        m = gc.get_message(svc, mid)
        if gc.match_broker(m["from_email"]) != want:
            continue
        done += 1
        body = m["plain"].strip() or parsers.html_to_text(m["html"])
        print("=" * 78)
        print(f"[{want}] {m['from_email']} | {m['date']}")
        print(f"SUBJECT: {m['subject']}")
        print(f"ATTACHMENTS: {[(a['filename'], a['mime']) for a in m['attachments']]}")
        print(f"BODY chars: {len(body)} (html {len(m['html'])})")
        print("-" * 78)
        data = parsers.ai_extract(body, source_label=f"{want} / {m['from_email']}")
        usage = data.pop("_usage", {})
        listings = data.get("listings", [])
        print(f"EXTRACTED {len(listings)} listing(s)  [tokens in/out: "
              f"{usage.get('in','?')}/{usage.get('out','?')}]")
        for L in listings:
            print(json.dumps(L, indent=2, ensure_ascii=False))
        if "_parse_error" in data:
            print("PARSE ERROR raw:", data["_parse_error"])
        if done >= n:
            break
    if done == 0:
        print(f"No messages found for broker_key '{want}'.")


if __name__ == "__main__":
    main()
