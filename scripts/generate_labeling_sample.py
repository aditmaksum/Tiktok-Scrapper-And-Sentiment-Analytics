"""Generate a random sample for manual sentiment labeling.

One-off dev tool, not part of the runtime pipeline. Requires openpyxl
(not in requirements.txt — install separately: pip install openpyxl).

Usage:
    python scripts/generate_labeling_sample.py [--force]
    python scripts/generate_labeling_sample.py --additional 300 \\
        --exclude-xlsx runs/2026-08/labeling_sample_labeled.xlsx \\
        --output local/labeling_sample_batch2.xlsx --seed 20260904

Output: local/labeling_sample.xlsx by default (gitignored - contains real
customer comment text, see docs/calibration/codebook.md and .gitignore's
local/ note for why this lives outside runs/ and is never committed).

--additional draws a NEW sample of that size, excluding every comment_id
already present in --exclude-xlsx (defaults to the Tahap B labeled file),
so a second labeling batch never re-labels the same 200 comments.
"""
import argparse
import csv
import os
import random

from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.datavalidation import DataValidation

SOURCE_CSV = "runs/2026-08/comments.csv"
OUTPUT_XLSX = "local/labeling_sample.xlsx"
SAMPLE_SIZE = 200
SEED = 20260830  # fixed seed -> reproducible sample across reruns
DEFAULT_EXCLUDE_XLSX = "local/labeling_sample_labeled.xlsx"

LABEL_OPTIONS = ["positif", "negatif", "netral", "tidak_yakin"]


def _load_excluded_ids(path: str) -> set[str]:
    wb = load_workbook(path, read_only=True)
    ws = wb.active
    headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    col = headers.index("comment_id")
    ids = set()
    for row in ws.iter_rows(min_row=2, values_only=True):
        value = row[col]
        if value is not None:
            ids.add(str(value).lstrip("'"))
    return ids


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true",
        help="overwrite the output file if it already exists (default: refuse)"
    )
    parser.add_argument(
        "--additional", type=int, default=None,
        help="draw this many NEW comments instead of the default %d, "
             "excluding ids already in --exclude-xlsx" % SAMPLE_SIZE
    )
    parser.add_argument(
        "--exclude-xlsx", default=DEFAULT_EXCLUDE_XLSX,
        help="labeled xlsx whose comment_ids must not appear in the new sample "
             "(only used with --additional; default: %s)" % DEFAULT_EXCLUDE_XLSX
    )
    parser.add_argument(
        "--output", default=OUTPUT_XLSX,
        help="output path (default: %s)" % OUTPUT_XLSX
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="RNG seed (default: %d for the base sample, must be set explicitly "
             "with --additional to avoid drawing the same 300 twice)" % SEED
    )
    args = parser.parse_args()

    output_path = args.output
    sample_size = args.additional if args.additional is not None else SAMPLE_SIZE
    exclude_ids: set[str] = set()

    if args.additional is not None:
        if args.seed is None:
            raise SystemExit("--additional requires --seed (pick a new one, e.g. today's date)")
        exclude_ids = _load_excluded_ids(args.exclude_xlsx)
    seed = args.seed if args.seed is not None else SEED

    if os.path.exists(output_path) and not args.force:
        raise SystemExit(
            f"{output_path} already exists - refusing to overwrite (would clobber any "
            "labeling in progress). Pass --force if you really mean to regenerate it."
        )

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    with open(SOURCE_CSV, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    if exclude_ids:
        rows = [r for r in rows if r["comment_id"] not in exclude_ids]

    if len(rows) < sample_size:
        raise ValueError(f"only {len(rows)} eligible comments available, need {sample_size}")

    rng = random.Random(seed)
    sample = rng.sample(rows, sample_size)

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
    dv.add(f"E2:E{sample_size + 1}")

    widths = {"A": 22, "B": 20, "C": 60, "D": 30, "E": 14, "F": 30}
    for col, width in widths.items():
        ws.column_dimensions[col].width = width

    wb.save(output_path)
    print(f"wrote {sample_size} rows to {output_path} (seed={seed})")


if __name__ == "__main__":
    main()
