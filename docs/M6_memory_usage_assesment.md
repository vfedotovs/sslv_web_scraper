# M6 Memory Usage Assessment

**Date:** 2026-07-09  
**File reviewed:** `src/ws/requirements.txt`

## Requirements Reviewed

```txt
uvicorn
fastapi
requests
bs4
pandas
sendgrid
psycopg2-binary
matplotlib
fpdf
plotly
boto3
tabulate
```

## Estimated Memory Consumption Ranking

Ranking is based on typical real-world RSS memory impact when imported in containerized Python services (biggest to smallest):

| Rank | Library            | Est. Memory Impact     | Notes |
|------|--------------------|------------------------|-------|
| 1    | **pandas**         | Very High (~150-280MB) | Heaviest. Pulls numpy + many C extensions. Core data processing. |
| 2    | **matplotlib**     | High (~80-140MB)       | Heavy plotting stack (even for light use). |
| 3    | **plotly**         | High (~70-120MB)       | Large library + dependencies. |
| 4    | **boto3**          | Medium-High (~50-90MB) | botocore loads large JSON service models. |
| 5    | **psycopg2-binary**| Medium (~30-50MB)      | Binary PostgreSQL driver. |
| 6    | **fastapi + uvicorn** | Medium (~35-65MB)   | Web framework + server (combined). |
| 7    | **sendgrid**       | Low-Medium (~20-35MB)| Email client. |
| 8    | **requests**       | Low (~12-20MB)         | Lightweight HTTP client. |
| 9    | **fpdf**           | Low (~8-15MB)          | PDF generation library. |
| 10   | **bs4**            | Low (~8-12MB)          | BeautifulSoup (HTML parsing). |
| 11   | **tabulate**       | Very Low (<8MB)        | Table formatting utility. |

## Key Observations

- **matplotlib** and **plotly** are **not imported anywhere** in `src/ws/`. They appear to be unused/dead weight in `requirements.txt`.
- **pandas** is the dominant memory consumer and is imported in many core modules (`df_cleaner.py`, `analytics.py`, `pdf_creator.py`, `db_worker.py`, `data_format_changer.py`, etc.).
- **boto3** is used in `file_downloader.py` and `aws_mailer.py`.
- **psycopg2** is used in `db_worker.py`.
- Heavy libraries (pandas, matplotlib, plotly, boto3) are often imported at module level, increasing base memory of the FastAPI process even when idle.
- The backup container (`src/backup-svc`) is already somewhat isolated, which is good.

## Low-Effort Recommendations to Reduce Memory

| Priority | Action | Effort | Expected Impact | Recommendation |
|----------|--------|--------|------------------|----------------|
| **Highest** | Remove unused libraries | Very Low | High | Remove `matplotlib` and `plotly` from `requirements.txt` immediately. |
| **High** | Lazy imports for heavy libs | Low | Medium-High | Move `import pandas as pd` and `import boto3` **inside** functions instead of top-level in modules. |
| **Medium** | Optimize boto3 usage | Low | Medium | Use lazy import + reuse a single `boto3.Session()` where possible. |
| **Medium** | Consider lighter pandas alternative | Medium | Medium-High | Evaluate `polars` for some data processing paths (lower memory footprint). |
| **Low** | Use non-interactive backend | Low | Medium | If matplotlib is ever re-enabled: `matplotlib.use('Agg')` + lazy import. |
| **Low** | Review psycopg2 | Low | Low | `psycopg2-binary` is already the lighter wheel. Alternative is `psycopg` (v3). |

### Quick Wins (Today)
1. Remove `matplotlib` and `plotly` from `requirements.txt`.
2. Apply lazy imports for `pandas` and `boto3` in the following files:
   - `df_cleaner.py`
   - `analytics.py`
   - `pdf_creator.py`
   - `data_format_changer.py`
   - `db_worker.py`
   - `run_analisys.py`
   - `file_downloader.py`
   - `aws_mailer.py`

## Additional Notes

- Memory impact was estimated based on typical container observations (not measured in this specific environment).
- For accurate measurement, run:
  ```bash
  docker stats
  python -c "import pandas as pd; import psutil, os; print(psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024, 'MB')"
  ```
- Consider measuring before/after any changes.
- The web service (FastAPI) base memory will always include `fastapi` + `uvicorn` + whatever is imported at startup.

## Next Suggested Steps

1. Remove unused heavy libraries.
2. Implement lazy imports for pandas and boto3.
3. Rebuild and measure memory usage of the `ws` container.
4. Evaluate moving heavy report generation (if any) into a separate lightweight worker if needed.

---

## Update (2026-07-12, branch dev-1.7.8)

Status re-check of the recommendations above against the current code:

### Requirements as of dev-1.7.8

```txt
uvicorn
fastapi
requests
bs4
pandas
psycopg2-binary
boto3
tabulate
pyyaml
```

### What has been done since the original assessment

- ✅ **Quick Win 1 completed** (commit `8eea050`): `matplotlib`, `plotly`,
  `sendgrid` and `fpdf` were removed from `requirements.txt`. The three
  heaviest unused libraries are gone (~150–250MB image/RSS weight).
- ✅ `pdf_creator.py` was decommissioned (commit `42c8d3c`) — no live
  matplotlib/fpdf code paths remain; the module file is dead code.
- ✅ M7 P1/P5 reduced the *data volume* pandas handles: the scraped
  DataFrame now contains only newly discovered ads (typically 2–5% of
  daily volume), not the full listing set, and per-hash full-frame
  iteration was removed.
- ➕ `pyyaml` was added (M6 Phase 4 `city_config.py`); it is imported
  lazily inside a try/except and is Low impact (<10MB).

### Corrections to the original file list

- `pdf_creator.py` and `run_analisys.py` are **not part of the live
  pipeline** (nothing imports them from `main.py` or the wsmodules used
  by it). They need no lazy-import work — they are candidates for
  deletion, not refactoring. Same for `next_features/DataAnalyser.py`
  and `sendgrid_mailer.py`.
- Live pandas importers today are exactly four modules:
  `data_format_changer.py`, `df_cleaner.py`, `db_worker.py`,
  `analytics.py`.

### Remaining open item

**pandas** is now the single dominant avoidable memory consumer
(~150–280MB RSS per `ws` container, multiplied by the one-container-per-
city deployment model). Its actual API usage in the live modules is
small (read_csv/to_csv, string cleanup, one sort, one group-by-column,
iterrows) and operates on ≤ a few thousand rows — stdlib `csv` +
plain dicts cover all of it. The removal is planned as **M8**: see
`m8_refactor_remove_pandas.md` for the phased action plan.
