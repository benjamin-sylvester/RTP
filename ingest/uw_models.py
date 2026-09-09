"""Read headline metrics out of a full Excel underwriting model.

Deployment-agnostic: everything works from a local file path, so the same code
serves a local scheduled run (Drive-for-Desktop mount) or a cloud run that has
downloaded the file via the Drive API first.

extract(path) scans the model's summary-style tabs for labeled figures and
returns {canonical, raw}:
  - raw: every labeled value found (audit trail; stored to model_stats jsonb)
  - canonical: the mapped subset we care about, each with its provenance

The models are institutional and idiosyncratic (Lakeside carries a development
scenario; Rochester is a plain value-add), so matching is tolerant and every
canonical value keeps a sheet!cell reference so a wrong pull can be traced.
"""
import glob
import os
import re
import openpyxl

# canonical field -> (ordered label patterns, kind). First match wins, so put
# the most specific label first. kind drives coercion + sanity bounds.
CANON = [
    ("purchase_price", [r"^purchase price$", r"^offer price$", r"^purchase price\b"], "money"),
    ("units",          [r"^total units?\b", r"^# ?of units", r"^unit count$"], "int"),
    ("in_place_cap",   [r"in.?place cap", r"going.?in cap", r"^adj\.? cap rate", r"^cap rate$"], "rate"),
    ("stabilized_cap", [r"stabilized cap", r"pro.?forma cap"], "rate"),
    ("exit_cap",       [r"exit cap"], "rate"),
    ("noi",            [r"in.?place noi", r"^net operating income", r"^noi\b", r"^noi$"], "money"),
    ("gpr",            [r"gross potential rent"], "money"),
    ("irr",            [r"^irr$", r"levered irr", r"^irr\b"], "rate"),
    ("equity_multiple",[r"^equity multiple", r"^moic$", r"^moic\b"], "ratio"),
    ("dscr",           [r"^dscr$", r"debt service coverage"], "ratio"),
    ("vacancy",        [r"^vacancy$", r"^vacancy\b"], "rate"),
    ("expense_ratio",  [r"expense ratio"], "ratio"),
]
# sheets most likely to hold the summary, scored highest first
_SUMMARY_HINT = re.compile(r"(sum|overview|return|output|dashboard|snapshot)", re.I)


def find_latest_model(deal_folder, analysis_sub="4.0 Investment Analysis"):
    """Given a deal folder (…/2.0 Underwriting/<deal>), return the newest UW
    workbook in its 4.0 Investment Analysis folder, or None.
    Prefers the highest _vNN; falls back to most-recently-modified."""
    base = os.path.join(deal_folder, analysis_sub)
    if not os.path.isdir(base):
        base = deal_folder  # some deals keep the model at the folder root
    files = [f for f in glob.glob(os.path.join(base, "*.xlsx"))
             if not os.path.basename(f).startswith("~$")]
    if not files:
        return None

    def ver(f):
        m = re.search(r"[_ ]v(\d+)\.xlsx$", os.path.basename(f), re.I)
        return int(m.group(1)) if m else -1
    files.sort(key=lambda f: (ver(f), os.path.getmtime(f)))
    best = files[-1]
    m = re.search(r"[_ ]v(\d+)\.xlsx$", os.path.basename(best), re.I)
    return {"path": best, "filename": os.path.basename(best),
            "version": (f"v{m.group(1)}" if m else None),
            "mtime": os.path.getmtime(best)}


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.replace(",", "").replace("$", "").replace("%", "").strip()
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _coerce(n, kind):
    """Bound-check by kind; return None if implausible so bad pulls don't land."""
    if n is None:
        return None
    if kind == "money":
        return round(n) if abs(n) >= 1000 else None
    if kind == "int":
        return int(round(n)) if 0 < n < 10000 else None
    if kind == "rate":              # stored as a fraction in Excel (6.69% -> 0.0669)
        return round(n, 5) if -1 < n < 1 else None
    if kind == "ratio":             # DSCR / equity multiple ~ 0.5–8
        return round(n, 4) if 0 < n < 20 else None
    return n


def _nearest_number(ws, cell):
    """First numeric value scanning right (up to 5 cols) then one row down."""
    for dc in range(1, 6):
        n = _num(ws.cell(row=cell.row, column=cell.column + dc).value)
        if n is not None:
            return n, ws.cell(row=cell.row, column=cell.column + dc).coordinate
    n = _num(ws.cell(row=cell.row + 1, column=cell.column).value)
    if n is not None:
        return n, ws.cell(row=cell.row + 1, column=cell.column).coordinate
    return None, None


def extract(path, max_row=120, max_col=30):
    """Return {'canonical': {...}, 'raw': [...]} for one model workbook."""
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    sheets = sorted(wb.worksheets, key=lambda s: 0 if _SUMMARY_HINT.search(s.title) else 1)
    raw, canon = [], {}
    for ws in sheets:
        for row in ws.iter_rows(min_row=1, max_row=max_row, max_col=max_col):
            for c in row:
                if not (isinstance(c.value, str) and 1 < len(c.value.strip()) < 46):
                    continue
                label = c.value.strip().replace("\n", " ")
                low = label.lower()
                num, at = _nearest_number(ws, c)
                if num is not None:
                    raw.append({"sheet": ws.title, "cell": c.coordinate,
                                "label": label, "value": num, "at": at})
                for key, pats, kind in CANON:
                    if key in canon:
                        continue
                    if any(re.search(p, low) for p in pats):
                        val = _coerce(num, kind)
                        if val is not None:
                            canon[key] = {"value": val, "sheet": ws.title,
                                          "cell": c.coordinate, "label": label, "kind": kind}
    wb.close()
    if canon.get("units") and canon.get("purchase_price"):
        canon["price_per_unit"] = {"value": round(canon["purchase_price"]["value"] / canon["units"]["value"]),
                                   "sheet": "derived", "cell": "", "label": "price/unit", "kind": "money"}
    return {"canonical": canon, "raw": raw}


def flat(canonical):
    """canonical dict -> {key: value} for storage/logging."""
    return {k: v["value"] for k, v in canonical.items()}
