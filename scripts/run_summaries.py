"""Phase 2 step 4 runner — generate AI summaries for pipeline deals (leads +
packages) and write to auto_underwriting.summary. Reads source email/OM text."""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _conn import connect
from ingest import gmail_client as gc, summarize


def main():
    svc = gc.service()
    with connect(autocommit=False) as conn:
        deals = conn.execute(
            "SELECT deal_kind, deal_id, name, market, state, effective_units, "
            "effective_ask FROM v_pipeline_deals").fetchall()
        print(f"Generating summaries for {len(deals)} pipeline deals...\n")
        for kind, did, name, market, state, units, ask in deals:
            au = conn.execute(
                "SELECT implied_cap_current, estimated_dscr, price_per_unit_vs_market, "
                "score, tier, score_confidence FROM auto_underwriting "
                f"WHERE {'package_id' if kind=='package' else 'listing_id'}=%s", (did,)
            ).fetchone()
            audict = dict(zip(["implied_cap_current", "estimated_dscr",
                               "price_per_unit_vs_market", "score", "tier",
                               "score_confidence"], au))
            deal = {"deal_kind": kind, "deal_id": did, "name": name, "market": market,
                    "state": state, "effective_units": units, "effective_ask_cents": ask}
            text = summarize.summarize(conn, svc, deal, audict)
            conn.execute(
                f"UPDATE auto_underwriting SET summary=%s "
                f"WHERE {'package_id' if kind=='package' else 'listing_id'}=%s",
                (text, did))
            print(f"[{audict['tier']} {audict['score']}] {name}, {market}")
            print(f"   {text}\n")
        conn.commit()


if __name__ == "__main__":
    main()
