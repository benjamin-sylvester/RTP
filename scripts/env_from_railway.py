"""Rebuild .env from a Railway variables dump.

`.env` is gitignored, so a fresh clone has none and Railway is the only place
the values still live. Accepts either format the CLI emits:

    railway variables --json > railway_vars.json
    railway variables       > railway_vars.txt      (KEY=VALUE or table)

Usage:
    python scripts/env_from_railway.py railway_vars.json [--force]

Writes .env in the repo root. Refuses to clobber an existing .env unless
--force is passed; the existing file is backed up either way.
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"

# Everything the app reads. Anything else in the dump is carried over too --
# this list only drives the completeness warning at the end.
REQUIRED = [
    "DATABASE_URL",
    "ANTHROPIC_API_KEY",
    "GMAIL_CLIENT_ID",
    "GMAIL_CLIENT_SECRET",
    "GMAIL_REFRESH_TOKEN",
]

OPTIONAL = [
    "CLAUDE_MODEL",
    "GMAIL_DEAL_FLOW_LABEL",
    "DISPATCH_EMAIL",
    "INGEST_INTERVAL_MINUTES",
    "INGEST_AFTER_FLOOR",
    "GOOGLE_MAPS_API_KEY",
    "DASHBOARD_PASSWORD",
    "DASHBOARD_SECRET_KEY",
    "DASHBOARD_HTTPS",
]


def parse_json(text):
    data = json.loads(text)
    # Railway has shipped both {"KEY": "value"} and [{"name":..,"value":..}].
    if isinstance(data, dict):
        return {k: str(v) for k, v in data.items()}
    if isinstance(data, list):
        out = {}
        for item in data:
            if isinstance(item, dict):
                name = item.get("name") or item.get("key")
                if name:
                    out[name] = str(item.get("value", ""))
        return out
    raise ValueError("unrecognized JSON shape")


def parse_text(text):
    """Handle plain KEY=VALUE lines and the CLI's box-drawn table."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # strip table borders: │ KEY │ VALUE │
        if line[0] in "|│╭╰├┌└├" or set(line) <= set("─═-+ │|╭╮╯╰┌┐┘└┤├"):
            line = line.strip("|│ ")
            parts = [p.strip() for p in re.split(r"[|│]", line) if p.strip()]
            if len(parts) >= 2 and re.fullmatch(r"[A-Z0-9_]+", parts[0]):
                out[parts[0]] = parts[1]
            continue
        m = re.match(r"^([A-Z][A-Z0-9_]*)\s*=\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv

    if not args:
        sys.exit(__doc__)

    src = pathlib.Path(args[0])
    if not src.exists():
        sys.exit(f"No such file: {src}")

    text = src.read_text(encoding="utf-8", errors="replace")
    try:
        values = parse_json(text)
    except Exception:
        values = parse_text(text)

    if not values:
        sys.exit(f"Could not parse any KEY=VALUE pairs out of {src}")

    # Railway exposes DATABASE_URL on the private network (*.railway.internal),
    # which does not resolve outside the project, plus DATABASE_PUBLIC_URL via
    # the TCP proxy. For local work we need the public one.
    db = values.get("DATABASE_URL", "")
    pub = values.get("DATABASE_PUBLIC_URL", "")
    if ".railway.internal" in db and pub:
        values["DATABASE_URL"] = pub
        values["DATABASE_INTERNAL_URL"] = db
        print("Note: DATABASE_URL pointed at the private network; swapped in "
              "DATABASE_PUBLIC_URL so it works from this machine.")
        print("      (the original is kept as DATABASE_INTERNAL_URL -- Railway "
              "services should keep using that one)")
    elif ".railway.internal" in db and not pub:
        print("WARNING: DATABASE_URL is a private-network host and no "
              "DATABASE_PUBLIC_URL was in the dump.")
        print("         It will not connect from this machine. In Railway, open "
              "the Postgres service -> Variables and copy DATABASE_PUBLIC_URL,")
        print("         or enable TCP proxying on the service.")

    if ENV.exists():
        backup = ROOT / ".env.backup"
        backup.write_text(ENV.read_text())
        if not force:
            sys.exit(f".env already exists (backed up to {backup.name}). "
                     f"Re-run with --force to overwrite.")
        print(f"Backed up existing .env -> {backup.name}")

    lines = [
        "# Reconstructed from a Railway variables dump.",
        "# Never commit this file.",
        "",
    ]
    for k in REQUIRED + OPTIONAL:
        if k in values:
            lines.append(f"{k}={values[k]}")
    extras = sorted(set(values) - set(REQUIRED) - set(OPTIONAL))
    if extras:
        lines += ["", "# Other vars carried over from Railway"]
        lines += [f"{k}={values[k]}" for k in extras]

    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {ENV} ({len(values)} variables)")

    missing = [k for k in REQUIRED if k not in values]
    if missing:
        print("\nWARNING - required keys absent from the dump:")
        for k in missing:
            print(f"  {k}")
        print("Check you dumped the right service (RTP-INGEST has the full set).")

    print("\nThis file now holds live secrets. Keep it out of git (.gitignore "
          "already covers it) and rotate the values once you are back up.")


if __name__ == "__main__":
    main()
