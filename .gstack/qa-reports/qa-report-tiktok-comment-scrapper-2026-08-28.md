# QA Report: tiktok-comment-scrapper

Date: 2026-08-28
Branch: master
Tier: Standard (low-severity findings were fixed anyway, see Triage)
Duration: ~25 minutes
Health score: **84 → 100**

## Scope note: no browser was used

`/qa` is built around a browser: navigate pages, click things, read the console.
This project has no web surface at all. It is a CLI (`main.py`, `batch.py`) plus
a scraper module. There is no server, no port, no HTML. Pointing a browser at it
would test nothing.

The user was told this before testing started and chose CLI scope. So "testing"
here means running the CLI against real and malformed input and watching what
breaks: bad CSVs, wrong ids, invalid flags, corrupt checkpoints. Evidence is
captured command output and exit codes rather than screenshots.

Everything else in the skill applied normally: triage by severity, minimal
fixes, one commit per fix, re-verification, regression tests, before/after
scoring.

## Summary

| | |
|---|---|
| Issues found | 4 |
| Fixed and verified | 4 |
| Deferred | 0 |
| Reverted | 0 |
| Tests added | 35 (this repo had none) |

Seventeen scenarios were run. Thirteen already behaved correctly and are listed
under Passed below.

## Issues

### ISSUE-001 - a comment cap of zero reports success and poisons the checkpoint

**Severity:** High
**Category:** Functional
**Fix status:** verified
**Commit:** `f82dac2`
**Files:** `batch.py`, `main.py`

`--max-comments=0` (also negative values, and `--size=0` on the single-video
CLI) collected nothing, wrote an empty dataset, and exited **0**, which every
script and every human reads as success.

Worse, the run still recorded each video in the checkpoint as finished. Rerunning
with a correct cap then skipped every one of them:

```
[1/1] skip 7418294751977327878 - already in checkpoint
done - 0 video(s) scraped this run, 1 total
```

The empty month was stuck there. Only `--fresh` could clear it, and nothing in
the output said so. For a job that runs overnight once a month, this is: come
back in the morning, read "done", ship an empty dataset.

**Repro (before fix):**
```
python batch.py --input=videos.csv --max-comments=0     # exit 0, empty output
python batch.py --input=videos.csv --max-comments=200   # skips everything
```

**Fix:** both caps are validated before any network call. A cap below 1, or a
negative reply cap, prints one line and exits 1.

**After fix:**
```
ERROR | --max-comments must be at least 1, got 0
exit=1
```
No output directory is created, and no request is sent.

---

### ISSUE-002 - malformed checkpoint entries reach the final output

**Severity:** Medium
**Category:** Functional
**Fix status:** verified
**Commit:** `4ff9d96`
**Files:** `tiktokcomment/runner.py`

Checkpoint lines were parsed as JSON and trusted. A line that parsed but was
incomplete (a half-written append after a power cut, a kill mid-write) kept its
id and lost its payload, then flowed straight into `comments.json` as a record
with no `comments` field:

```
entries: 2
  aweme_id='111'                  keys: ['account_type', 'aweme_id']
  aweme_id=None                   keys: 1
```

An analyst loading that file gets records that break whatever reads them next.

Lines that failed to parse were dropped with `continue` and no message, so a
truncated checkpoint lost videos silently during the exact recovery it exists to
support.

**Fix:** an entry now needs an id and a `comments` list to count, and the number
of unreadable lines is reported.

**After fix:**
```
WARNING | 3 unreadable line(s) in ...partial.jsonl were ignored - those videos
          will be scraped again
entries: 1
  aweme_id='7418294751977327878'  comments=3  valid=True
```

---

### ISSUE-003 - a bad delay value leaks a raw Python message

**Severity:** Low
**Category:** UX
**Fix status:** verified
**Commit:** `f82dac2`
**Files:** `batch.py`

`--video-delay=a,b` passed the field-count check, then failed inside `float()`:

```
ERROR | could not convert string to float: 'a'
```

That names neither the flag nor the format it wants. **Fix:** the conversion is
caught and reported as `delay must be two numbers as MIN,MAX - got 'a,b'`.

---

### ISSUE-004 - `--month` can write outside the output directory

**Severity:** Low
**Category:** Functional
**Fix status:** verified
**Commit:** `f82dac2`
**Files:** `batch.py`

`--month` went straight into `os.path.join`, so a value containing `..` escaped
`--output`. Confirmed: `--month=../../ketembak` created `/tmp/ketembak`, well
outside the requested directory, while the log cheerfully reported success.

Self-inflicted rather than an attack: the operator runs this on their own
machine with their own flags. The cost is a typo scattering a month's output
somewhere they will not think to look. **Fix:** a `--month` containing a path
separator or `..` is rejected.

## Triage

Standard tier fixes critical, high, and medium, and defers low.

ISSUE-003 and ISSUE-004 are low, and were fixed anyway. Both are a few lines,
both sit in the same argument-validation block as the ISSUE-001 fix, and both
are traps rather than cosmetics: one hands the operator a message that does not
name the problem, the other loses their output. Deferring them would have cost
more than fixing them.

## Passed

These behaved correctly with no change needed:

| Scenario | Result |
|---|---|
| CSV missing the required column | clean error naming the expected header, exit 2 |
| CSV with a header and no rows | `no usable rows`, exit 1 |
| CSV rows holding only spaces or tabs | each skipped with its line number |
| CSV with a UTF-8 BOM | parsed correctly |
| CSV with extra columns in a different order | parsed correctly |
| `account_type` left blank | defaults to `unknown`, video still scraped |
| `account_type` column absent entirely | defaults to `unknown` |
| Duplicate video, given once as an id and once as a URL | second skipped as duplicate |
| Video id that returns nothing | warned, batch continues |
| `--input` pointing at a missing file | click's own error, exit 2 |
| `--video-delay` with MIN greater than MAX | rejected with bounds message |
| Resume after a completed run | every video skipped from checkpoint |
| `--fresh` | checkpoint cleared, everything rescraped |

## Regression tests

**Commit:** `f7575d2`

This repo had no tests and no test framework. Added pytest, `pytest.ini`, a
`conftest.py`, and 35 tests across two files. The whole suite runs offline in
about one second: nothing in it reaches TikTok.

`conftest.py` carries a loguru sink fixture. pytest's `capsys` and `capfd` cannot
see loguru output, because loguru's default handler holds the `sys.stderr` object
from import time, before pytest installs its capture. Two rounds of test failures
came from that before the sink fixture replaced them.

**The tests were checked against the broken code.** With the ISSUE-001 cap check
disabled, `test_batch_rejects_non_positive_max_comments` fails on all three
parameters, and its captured log reproduces the original bug exactly: zero
comments collected, a `done` line, output written as if the run had worked. That
run also took 88 seconds because it reached the network, against 3 seconds with
the fix in place, which is a second measure of what the fix prevents.

## Health score

Browser-only categories (Links, Visual, Accessibility) do not apply to a CLI, so
the remaining weights were normalised across what does apply.

| Category | Weight | Before | After |
|---|---|---|---|
| Error output (leaked internal messages) | 15% | 70 | 100 |
| Functional | 20% | 74 | 100 |
| UX | 15% | 97 | 100 |
| Performance | 10% | 100 | 100 |
| Content | 5% | 100 | 100 |
| **Weighted total** | | **84** | **100** |

## Still open

Not bugs, but worth knowing:

- **`origin` points at the upstream author's repository**, not a fork of the
  user's own: `github.com/romysaputrasihananda/tiktok-comment-scrapper`. The
  design doc committed in `b0f9a59` carries internal context about how this data
  drives campaign decisions. Point `origin` at your own fork before pushing.
- **No CI.** The suite runs locally only. A GitHub Actions workflow would take a
  few minutes to add if the repo ever gets one.
- **Phase 2 and Phase 3 are unbuilt.** The Playwright fallback and discovery by
  username are designed but not written, so nothing here tests them.

## PR summary

QA found 4 issues, fixed 4, health score 84 → 100. Added the repo's first test
suite: 35 offline regression tests.
