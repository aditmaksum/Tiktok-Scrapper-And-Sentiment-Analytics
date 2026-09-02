"""Generate 200-comment random sample for manual sentiment labeling (Tahap B).

One-off dev tool, not part of the runtime pipeline. Requires openpyxl
(not in requirements.txt — install separately: pip install openpyxl).

Usage:
    python scripts/generate_labeling_sample.py [--force]

Output: local/labeling_sample.xlsx (gitignored - contains real customer
comment text, see docs/calibration/codebook.md and .gitignore's local/ note
for why this lives outside runs/ and is never committed).
"""
import argparse
import csv
import os
import random

from openpyxl import Workbook
from openpyxl.worksheet.datavalidation import DataValidation

SOURCE_CSV = "runs/2026-08/comments.csv"
OUTPUT_XLSX = "local/labeling_sample.xlsx"
SAMPLE_SIZE = 200
SEED = 20260830  # fixed seed -> reproducible sample across reruns

LABEL_OPTIONS = ["positif", "negatif", "netral", "tidak_yakin"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true",
        help="overwrite the output file if it already exists (default: refuse)"
    )
    args = parser.parse_args()

    if os.path.exists(OUTPUT_XLSX) and not args.force:
        raise SystemExit(
            f"{OUTPUT_XLSX} already exists - refusing to overwrite (would clobber any "
            "labeling in progress). Pass --force if you really mean to regenerate it."
        )

    os.makedirs(os.path.dirname(OUTPUT_XLSX), exist_ok=True)

    with open(SOURCE_CSV, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    if len(rows) < SAMPLE_SIZE:
        raise ValueError(f"only {len(rows)} comments available, need {SAMPLE_SIZE}")

    rng = random.Random(SEED)
    sample = rng.sample(rows, SAMPLE_SIZE)

    wb = Workbook()
    ws = wb.active
    ws.title = "labeling"

    headers = ["comment_id", "username", "comment", "video_url", "sentiment_label", "notes"]
    ws.append(headers)

    for row in sample:
        comment_id = row["comment_id"]
        ws.append([
            f"'{comment_id}",  # force text, prevents Excel scientific-notation truncation
            row["username"],
            row["comment"],
            row["video_url"],
            "",
            "",
        ])

    # comment_id column as text explicitly too, belt-and-suspenders vs Excel auto-detect
    for cell in ws["A"][1:]:
        cell.number_format = "@"

    dv = DataValidation(
        type="list",
        formula1=f'"{",".join(LABEL_OPTIONS)}"',
        allow_blank=True,
        showDropDown=False,  # False = show the dropdown arrow (openpyxl quirk)
    )
    dv.error = "Pilih salah satu: " + ", ".join(LABEL_OPTIONS)
    dv.errorTitle = "Label tidak valid"
    ws.add_data_validation(dv)
    dv.add(f"E2:E{SAMPLE_SIZE + 1}")

    widths = {"A": 22, "B": 20, "C": 60, "D": 30, "E": 14, "F": 30}
    for col, width in widths.items():
        ws.column_dimensions[col].width = width

    wb.save(OUTPUT_XLSX)
    print(f"wrote {SAMPLE_SIZE} rows to {OUTPUT_XLSX} (seed={SEED})")


if __name__ == "__main__":
    main()
