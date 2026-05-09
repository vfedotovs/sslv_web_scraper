# aws_mailer.py — Review & Action Items

Generated: 2026-05-09
File: `src/ws/app/wsmodules/aws_mailer.py`

---

## Status

| PR | Scope | Items | Status |
|---|---|---|---|
| #419 | Correctness bugs | BUG-1, BUG-2 (+ DEAD-1), BUG-3, BUG-4 | Open |
| #TBD | Docs / typos / cleanup | DOC-1, DOC-2, DOC-3, TYPO-1, TYPO-2, TYPO-3, DEAD-2, RF-1 | Open |
| Future | Architectural cleanup | RF-2, RF-3, RF-4, RF-5 | Deferred |

---

## Done

### BUG-1: SENDER/RECIPIENT from env (PR #419)
Replaced hardcoded `info@propertydata.lv` literals with `os.environ.get('SRC_EMAIL', ...)` and `os.environ.get('DEST_EMAIL', ...)`. Env vars were already plumbed through `docker-compose.yml` and `.env.prod`, just unused.

### BUG-2: Crash on missing `email_body_txt_m4.txt` (PR #419)
Replaced raw `with open(...)` with `extract_file_contents()` which already has the right error handling. Side effect: resolves DEAD-1 (function is now actually called).

### BUG-3: `e.strerror` can be `None` (PR #419)
Changed `log.error(f" {e.strerror} ")` to `log.error(f"Failed to delete {file}: {e}")` — full exception always renders, includes the filename being processed.

### BUG-4: Duplicate stdout output (PR #419)
Removed `print()` calls; the logger's `StreamHandler(sys.stdout)` already covers stdout, so each result was appearing twice in container logs.

### DEAD-1: `extract_file_contents` was unused (PR #419)
Resolved as a side effect of BUG-2 — the function is now called for the main email body.

### DOC-1: Module docstring rewrite (this PR)
Replaced the broken task list (which skipped task 2 and contained typos) with a one-paragraph purpose summary and a list of required env vars with their fallbacks.

### DOC-2: `remove_tmp_files` docstring (this PR)
Replaced `"""FIXME: Refactor this function to better code"""` with a descriptive PEP-257-style docstring including Args section.

### DOC-3: `gen_subject_title` docstring (this PR)
Added Returns section documenting the subject string format. Cleaned up the prose.

### TYPO-1: Module docstring typos (this PR)
`environemt`, `varibales`, `medatada` — all gone with the docstring rewrite.

### TYPO-2: Log string typos (this PR)
- `"Creating AWS SES clinet using boto3 "` → `"Creating AWS SES client using boto3"`
- `"Trying to sent email with AWS SES clinet using boto3 "` → `"Trying to send email with AWS SES client using boto3"`
- `"--- AWS SES mailer module completed with succeess ---"` → `"--- AWS SES mailer module completed with success ---"`

### TYPO-3: Module docstring task list numbering (this PR)
Resolved by DOC-1 — the broken task list is gone.

### DEAD-2: Unused `RotatingFileHandler` import (this PR)
Removed `from logging.handlers import RotatingFileHandler` — `RotatingFileHandler` is referenced via `handlers.RotatingFileHandler`, the unqualified name was never used.

### RF-1: AWS region from env (this PR)
`AWS_REGION = "eu-west-1"  # e.g., Ireland` → `AWS_REGION = os.environ.get('AWS_REGION', 'eu-west-1')`.

---

## Remaining (deferred to future PR)

### RF-2: Module-level logging handler setup
**Lines 30-42 (current state)**: handlers are attached at import time. Multiple imports → multiple handlers → file-descriptor leak. Currently mitigated by the `atexit` cleanup in `main.py` that walks all loggers, so not urgent.

**Fix**: move handler setup into a `_configure_logging()` function called once from `aws_mailer_main()`, gated by a "configured" flag.

### RF-3: Log file path is cwd-dependent
**Line 39 (current state)**: `RotatingFileHandler("aws_mailer.log", ...)` — relative path. If cwd changes between callers, the log lands in different directories or fails silently.

**Fix**: anchor to a known location, e.g. `os.path.join(os.path.dirname(__file__), '..', 'logs', 'aws_mailer.log')`, or make it env-driven.

### RF-4: Hardcoded filename lists drift
The module-level `data_files` and the in-function `extra_files` overlap (`basic_price_stats.txt`, `email_body_add_dates_table.txt` appear in both). Two sources of truth for "what files this module touches" — easy to drift when new files are added by `df_cleaner.py` or `db_worker.py`.

**Fix**: consolidate into one list, or generate from a glob pattern.

### RF-5: Bare `except Exception` in `extract_file_contents`
**Lines 138-144 (current state)**: catches everything, returns a friendly string. Hides bugs (e.g. encoding errors, permission issues) by masking them as "file not found".

**Fix**: catch only the specific exceptions expected (`UnicodeDecodeError`, `PermissionError`); let the rest propagate.

---

## Future-PR priority

| Priority | ID | Item | Effort | Reason |
|---|---|---|---|---|
| 1 | RF-3 | Anchor log file path | 3 lines | Same anti-pattern across project; surfaces silently |
| 2 | RF-5 | Narrow `except Exception` in `extract_file_contents` | 3 lines | Hides real bugs |
| 3 | RF-4 | Consolidate filename lists | 5 lines | Drift risk; not breaking |
| 4 | RF-2 | Move logging setup into a function | ~10 lines | Already mitigated by `main.py` atexit cleanup |
