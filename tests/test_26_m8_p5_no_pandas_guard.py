"""M8 Phase 5: guard tests keeping pandas out of the ws service.

The whole point of M8 was removing the ~150-280MB pandas+numpy import
cost from every per-city ws container. These tests fail loudly if
anyone reintroduces it — via a module import or via requirements.txt.
"""
import os

WS_APP_DIR = os.path.join(os.path.dirname(__file__), "..", "src", "ws", "app")
REQUIREMENTS = os.path.join(os.path.dirname(__file__), "..", "src", "ws",
                            "requirements.txt")


def iter_app_python_files():
    for dirpath, _dirnames, filenames in os.walk(WS_APP_DIR):
        if "__pycache__" in dirpath:
            continue
        for filename in filenames:
            if filename.endswith(".py"):
                yield os.path.join(dirpath, filename)


def test_no_ws_app_module_imports_pandas():
    offenders = []
    for path in iter_app_python_files():
        with open(path, encoding="utf-8") as fh:
            for line_number, line in enumerate(fh, start=1):
                stripped = line.strip()
                if stripped.startswith("import pandas") or \
                        stripped.startswith("from pandas"):
                    offenders.append(f"{path}:{line_number}: {stripped}")
    assert offenders == [], (
        "pandas import found in ws app code — M8 removed pandas"
        " (~150-280MB RSS per container); use stdlib csv instead:\n"
        + "\n".join(offenders)
    )


def test_ws_requirements_do_not_include_pandas():
    with open(REQUIREMENTS, encoding="utf-8") as fh:
        packages = [line.strip().lower() for line in fh if line.strip()]
    assert not any(pkg.startswith("pandas") or pkg.startswith("numpy")
                   for pkg in packages), (
        "pandas/numpy found in src/ws/requirements.txt — M8 removed them"
    )


def test_sanity_guard_scans_the_live_modules():
    """The walk must actually cover the four refactored modules."""
    scanned = {os.path.basename(p) for p in iter_app_python_files()}
    for module in ("data_format_changer.py", "df_cleaner.py",
                   "db_worker.py", "analytics.py", "main.py"):
        assert module in scanned
