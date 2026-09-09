"""Daily UW-model sync — pull the latest underwriting figures into the DB.

For every active deal that has a uw_folder, find its newest model in
<UW_ROOT>/<uw_folder>/4.0 Investment Analysis, extract the headline metrics, and
write them to auto_underwriting (+ listing_financials NOI/cap). Idempotent:
re-running with an unchanged model changes nothing; a revised model logs each
changed figure to listing_history.

  python scripts/sync_uw.py           # apply
  python scripts/sync_uw.py --dry     # preview, write nothing

UW_ROOT env var overrides the default Drive-for-Desktop path.
"""
import json
import os
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _conn import connect
from ingest import uw_models

DEFAULT_ROOT = r"G:\Shared drives\RTP G-Drive\2.0 Acquisitions\2.0 Underwriting"
UW_ROOT = os.environ.get("UW_ROOT", DEFAULT_ROOT)
DRY = "--dry" in sys.argv

# canonical extract key -> auto_underwriting column, for the HIGH-CONFIDENCE
# subset only. Cleanly-labeled fields land in typed columns; scenario-dependent
# return metrics (IRR, equity multiple, DSCR) stay in model_stats until the
# return-pull is per-deal targeted, so a hurdle rate never masquerades as the
# deal IRR in a headline column.
AU_MAP = {"in_place_cap": "implied_cap_current", "stabilized_cap": "implied_cap_stabilized"}


def sync_one(conn, lid, address, ref, log, mode="local", svc=None, dry=False):
    """ref is a local folder name (mode='local') or a Drive folder id (mode='drive')."""
    if mode == "drive":
        from ingest import drive_client
        latest = drive_client.latest_model(svc, ref)
        if not latest:
            log(f"  #{lid} {address}: no model in Drive folder {ref}")
            return "no_model"
        handle = drive_client.download(svc, latest["id"])
        filename, version = latest["filename"], latest["version"]
        mtime = datetime.fromisoformat(latest["modifiedTime"].replace("Z", "+00:00"))
    else:
        folder = os.path.join(UW_ROOT, ref)
        if not os.path.isdir(folder):
            log(f"  #{lid} {address}: folder not found — {folder}")
            return "no_folder"
        latest = uw_models.find_latest_model(folder)
        if not latest:
            log(f"  #{lid} {address}: no .xlsx model in 4.0 Investment Analysis")
            return "no_model"
        handle = latest["path"]
        filename, version = latest["filename"], latest["version"]
        mtime = datetime.fromtimestamp(latest["mtime"], timezone.utc)

    res = uw_models.extract(handle)
    flat = uw_models.flat(res["canonical"])
    if not flat:
        log(f"  #{lid} {address}: model found but no metrics extracted ({filename})")
        return "no_metrics"

    # prior synced values, to log only what actually moved
    prior_row = conn.execute(
        "SELECT model_stats FROM auto_underwriting WHERE listing_id=%s", (lid,)).fetchone()
    prior = (prior_row[0] or {}).get("canonical", {}) if prior_row and prior_row[0] else {}

    show = ", ".join(f"{k}={_fmt(k,v)}" for k, v in flat.items())
    log(f"  #{lid} {address}  [{filename}]")
    log(f"       {show}")
    for k, v in flat.items():
        pv = prior.get(k)
        if pv is None:
            log(f"       + {k}: {_fmt(k,v)}")
        elif pv != v:
            log(f"       ~ {k}: {_fmt(k,pv)} -> {_fmt(k,v)}")

    if dry:
        return "dry"

    stats = {"canonical": flat,
             "provenance": {k: f"{d['sheet']}!{d['cell']}" for k, d in res["canonical"].items()},
             "raw_count": len(res["raw"])}
    cols = {AU_MAP[k]: flat[k] for k in AU_MAP if k in flat}
    # update-or-insert auto_underwriting (listing_id is a FK, not a PK — the table
    # also serves packages — so ON CONFLICT has no unique target; do it explicitly)
    fields = ["model_file", "model_version", "model_modified", "model_synced_at", "model_stats"] + list(cols)
    vals = [filename, version, mtime, datetime.now(timezone.utc),
            json.dumps(stats)] + [cols[c] for c in cols]
    setclause = ", ".join(f"{f}=%s" for f in fields)
    n = conn.execute(f"UPDATE auto_underwriting SET {setclause} WHERE listing_id=%s",
                     (*vals, lid)).rowcount
    if not n:
        conn.execute(
            f"INSERT INTO auto_underwriting (listing_id, {', '.join(fields)}) "
            f"VALUES (%s, {', '.join(['%s']*len(fields))})", (lid, *vals))
    # NOI + cap into listing_financials (model is authoritative here)
    if "noi" in flat or "in_place_cap" in flat:
        conn.execute(
            "INSERT INTO listing_financials (listing_id, noi, cap_rate, data_source, confidence) "
            "VALUES (%s,%s,%s,'uw_model','high') ON CONFLICT (listing_id) DO UPDATE SET "
            "noi=COALESCE(EXCLUDED.noi, listing_financials.noi), "
            "cap_rate=COALESCE(EXCLUDED.cap_rate, listing_financials.cap_rate), "
            "data_source='uw_model', confidence='high'",
            (lid, round(flat["noi"] * 100) if "noi" in flat else None, flat.get("in_place_cap")))
    # log moved figures
    for k, v in flat.items():
        pv = prior.get(k)
        if pv != v:
            conn.execute(
                "INSERT INTO listing_history (listing_id, field, old_value, new_value) "
                "VALUES (%s,%s,%s,%s)", (lid, f"uw.{k}", None if pv is None else str(pv), str(v)))
    conn.commit()
    return "synced"


def _fmt(k, v):
    if v is None:
        return "—"
    if k in ("in_place_cap", "stabilized_cap", "exit_cap", "irr", "vacancy", "expense_ratio"):
        return f"{v*100:.1f}%"
    if k in ("equity_multiple", "dscr"):
        return f"{v:.2f}x"
    if k in ("purchase_price", "noi", "gpr", "price_per_unit"):
        return f"${v:,.0f}"
    return str(v)


def run_sync(mode=None, dry=False, log=print):
    """Sync the latest UW model for every active deal. mode 'drive' reads via the
    Google Drive API (the cloud path); 'local' reads the Drive-for-Desktop mount.
    Callable from daily_job (the daily cron) or the CLI. Returns a tally dict."""
    mode = (mode or os.environ.get("SYNC_SOURCE", "local")).lower()
    conn = connect()
    svc = None
    if mode == "drive":
        from ingest import drive_client
        svc = drive_client.service()
        col, where, src = "drive_folder_id", "drive_folder_id IS NOT NULL AND drive_folder_id <> ''", "Google Drive API"
    else:
        col, where, src = "uw_folder", "uw_folder IS NOT NULL AND uw_folder <> ''", f"local mount: {UW_ROOT}"
    rows = conn.execute(
        f"SELECT id, address, {col} FROM listings WHERE {where} "
        "AND status IN ('underwriting','loi_sent','under_contract','lead') "
        "ORDER BY id").fetchall()
    log(f"[uw-sync] {'(DRY) ' if dry else ''}[{mode}] {len(rows)} deal(s) — {src}")
    tally = {}
    for lid, addr, ref in rows:
        try:
            r = sync_one(conn, lid, addr, ref, log, mode=mode, svc=svc, dry=dry)
        except Exception as e:
            log(f"  #{lid} {addr}: ERROR {type(e).__name__}: {e}")
            r = "error"
        tally[r] = tally.get(r, 0) + 1
    log(f"[uw-sync] done: {tally}")
    conn.close()
    return tally


def main():
    run_sync(dry=DRY)


if __name__ == "__main__":
    main()
