"""Inspect the seed workbook so we can map columns to the schema."""
import sys
import pandas as pd
from _conn import ROOT

path = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "RTP_Deal_Database.xlsx")
xl = pd.ExcelFile(path)
print("FILE:", path.name)
print("SHEETS:", xl.sheet_names, "\n")
for sheet in xl.sheet_names:
    df = pd.read_excel(path, sheet_name=sheet)
    print(f"=== sheet '{sheet}' — {df.shape[0]} rows x {df.shape[1]} cols ===")
    print("COLUMNS:", list(df.columns))
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(df.head(4).to_string())
    print()
