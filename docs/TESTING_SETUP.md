# Testing Setup Guide

Complete guide for setting up the Python testing environment using `uv` and `pytest`.

## Quick Start

### 1. Install uv (if not already installed)

**macOS/Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Or with pip:**
```bash
pip install uv
```

**Verify installation:**
```bash
uv --version
```

### 2. Setup Virtual Environment

```bash
# Create venv and install pytest + pytest-cov
make setup-venv
```

**What this does:**
- ✅ Creates `.venv/` directory with Python virtual environment
- ✅ Installs `pytest` for running tests
- ✅ Installs `pytest-cov` for code coverage reports
- ✅ Shows installed packages

### 3. Activate Virtual Environment

```bash
source .venv/bin/activate
```

Your prompt should change to show `(.venv)` prefix.

### 4. Run Tests

```bash
# With Makefile (venv automatically detected)
make test-venv

# Or activate venv and run directly
source .venv/bin/activate
pytest -v
```

---

## Available Make Targets

### View All Commands

```bash
make help
```

### Virtual Environment Commands

| Command | Description |
|---------|-------------|
| `make setup-venv` | 🐍 Create venv with uv, install pytest & pytest-cov |
| `make clean-venv` | 🧹 Remove virtual environment |
| `make venv-info` | ℹ️  Show venv info and installed packages |
| `make test-venv` | 🧪 Run tests using venv |
| `make test-cov-venv` | 📊 Run tests with coverage report |
| `make install-dev` | 📦 Install dev dependencies (black, flake8, etc.) |

---

## Detailed Usage

### Setup Virtual Environment

```bash
make setup-venv
```

**Output:**
```
Setting up Python virtual environment with uv...
✅ uv found: uv 0.1.0
Creating virtual environment at .venv...
✅ Virtual environment created
Installing pytest and pytest-cov...
✅ pytest and pytest-cov installed

Virtual environment setup complete!

To activate the virtual environment:
  source .venv/bin/activate

Installed packages:
Package      Version
------------ -------
pytest       7.4.3
pytest-cov   4.1.0
...
```

### Run Tests

**Basic test run:**
```bash
make test-venv
```

**With coverage report:**
```bash
make test-cov-venv
```

**Coverage report will be saved to:**
- Terminal output (with missing lines highlighted)
- `htmlcov/index.html` (detailed HTML report)

**View HTML coverage report:**
```bash
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

### Install Development Tools

```bash
make install-dev
```

**Installs:**
- `black` - Code formatter
- `flake8` - Linter
- `mypy` - Type checker
- `isort` - Import sorter
- `pylint` - Code analyzer

**Or create `requirements-dev.txt` with custom dependencies:**
```txt
black==23.12.0
flake8==7.0.0
mypy==1.8.0
isort==5.13.2
pylint==3.0.3
pytest-asyncio==0.23.2
pytest-mock==3.12.0
```

Then run:
```bash
make install-dev
```

### Clean Up Virtual Environment

```bash
make clean-venv
```

**When to use:**
- Corrupted venv
- Need fresh install
- Python version changed
- Switching projects

**After cleaning, recreate:**
```bash
make setup-venv
```

### Check Virtual Environment Info

```bash
make venv-info
```

**Output:**
```
Virtual environment: .venv
Python: Python 3.11.6

Installed packages:
Package      Version
------------ -------
pytest       7.4.3
pytest-cov   4.1.0
...
```

---

## Writing Tests

### Test Structure

Create tests in `tests/` directory:

```
project/
├── src/
│   └── ws/
│       └── app/
│           └── main.py
├── tests/
│   ├── __init__.py
│   ├── test_main.py
│   └── test_wsmodules/
│       ├── __init__.py
│       ├── test_file_downloader.py
│       └── test_db_worker.py
└── pytest.ini
```

### Example Test

**tests/test_main.py:**
```python
import pytest
from src.ws.app.main import home, log_memory_usage

def test_home_endpoint():
    """Test the home endpoint returns correct response"""
    response = home()
    assert response == {"FastAPI server is ready !!!"}

def test_log_memory_usage(capsys):
    """Test memory logging function"""
    log_memory_usage()
    captured = capsys.readouterr()
    assert "Memory usage:" in captured.out
```

### pytest Configuration

**pytest.ini:**
```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --strict-markers
markers =
    slow: marks tests as slow
    integration: marks tests as integration tests
    unit: marks tests as unit tests
```

### Coverage Configuration

**.coveragerc:**
```ini
[run]
source = src
omit =
    */tests/*
    */venv/*
    */.venv/*
    */migrations/*

[report]
exclude_lines =
    pragma: no cover
    def __repr__
    raise AssertionError
    raise NotImplementedError
    if __name__ == .__main__.:
```

---

## Running Tests

### Basic Commands

```bash
# Activate venv first
source .venv/bin/activate

# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_main.py

# Run specific test function
pytest tests/test_main.py::test_home_endpoint

# Run tests matching pattern
pytest -k "memory"

# Run tests with specific marker
pytest -m unit
```

### Coverage Commands

```bash
# Run with coverage
pytest --cov=src

# Coverage with missing lines
pytest --cov=src --cov-report=term-missing

# Generate HTML report
pytest --cov=src --cov-report=html

# Generate multiple reports
pytest --cov=src --cov-report=term-missing --cov-report=html --cov-report=xml
```

### Using Makefile

```bash
# Run tests (checks venv exists)
make test-venv

# Run with coverage
make test-cov-venv
```

---

## Continuous Integration

### GitHub Actions Example

**.github/workflows/tests.yml:**
```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh

      - name: Setup virtual environment
        run: make setup-venv

      - name: Run tests
        run: make test-venv

      - name: Run tests with coverage
        run: make test-cov-venv

      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          files: ./coverage.xml
```

### GitLab CI Example

**.gitlab-ci.yml:**
```yaml
test:
  image: python:3.11
  before_script:
    - curl -LsSf https://astral.sh/uv/install.sh | sh
    - export PATH="$HOME/.cargo/bin:$PATH"
    - make setup-venv
  script:
    - make test-venv
    - make test-cov-venv
  coverage: '/(?i)total.*? (100(?:\.0+)?\%|[1-9]?\d(?:\.\d+)?\%)$/'
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
```

---

## Troubleshooting

### Issue: uv not found

**Error:**
```
❌ Error: uv is not installed
```

**Solution:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# Or
pip install uv
```

### Issue: Virtual environment already exists

**Error:**
```
⚠️  Virtual environment already exists at .venv
```

**Solution:**
```bash
# Remove old venv
make clean-venv

# Create new one
make setup-venv
```

### Issue: Tests not found

**Error:**
```
collected 0 items
```

**Solution:**
1. Ensure tests are in `tests/` directory
2. Test files must start with `test_`
3. Test functions must start with `test_`

```bash
# Check test discovery
pytest --collect-only
```

### Issue: Module import errors

**Error:**
```
ModuleNotFoundError: No module named 'src'
```

**Solution:**

**Option 1: Add to PYTHONPATH**
```bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src/ws"
```

**Option 2: Install in editable mode**
```bash
source .venv/bin/activate
pip install -e src/ws/
```

**Option 3: Use pytest.ini**
```ini
[pytest]
pythonpath = src/ws
```

### Issue: Permission denied

**Error:**
```
Permission denied: '.venv'
```

**Solution:**
```bash
# Check ownership
ls -la .venv

# Fix permissions
sudo chown -R $USER:$USER .venv
chmod -R 755 .venv
```

---

## Best Practices

### 1. Always Use Virtual Environment

```bash
# Bad - system-wide installation
pytest

# Good - use venv
source .venv/bin/activate
pytest

# Better - use Makefile
make test-venv
```

### 2. Keep Dependencies Updated

```bash
# Check for updates
source .venv/bin/activate
pip list --outdated

# Update specific package
uv pip install --python .venv/bin/python --upgrade pytest

# Recreate venv for major updates
make clean-venv
make setup-venv
```

### 3. Use Coverage Thresholds

**pytest.ini:**
```ini
[pytest]
addopts = --cov=src --cov-fail-under=80
```

**This will fail if coverage < 80%**

### 4. Organize Tests by Module

```
tests/
├── test_main.py              # Main app tests
├── test_wsmodules/
│   ├── test_file_downloader.py
│   ├── test_web_scraper.py
│   ├── test_db_worker.py
│   └── test_analytics.py
└── fixtures/
    └── conftest.py           # Shared fixtures
```

### 5. Use Test Markers

```python
import pytest

@pytest.mark.slow
def test_large_dataset():
    pass

@pytest.mark.integration
def test_database_connection():
    pass
```

**Run specific markers:**
```bash
# Run only fast tests
pytest -m "not slow"

# Run integration tests
pytest -m integration
```

---

## Additional Resources

### pytest Documentation
- **Official Docs:** https://docs.pytest.org/
- **Fixtures:** https://docs.pytest.org/en/latest/how-to/fixtures.html
- **Parametrize:** https://docs.pytest.org/en/latest/how-to/parametrize.html

### pytest-cov Documentation
- **Official Docs:** https://pytest-cov.readthedocs.io/
- **Coverage.py:** https://coverage.readthedocs.io/

### uv Documentation
- **Official Docs:** https://github.com/astral-sh/uv
- **Installation:** https://github.com/astral-sh/uv#installation

---

## Quick Reference

```bash
# Setup
make setup-venv              # Create venv with pytest
source .venv/bin/activate    # Activate venv
make install-dev             # Install dev tools

# Testing
make test-venv              # Run tests
make test-cov-venv          # Run with coverage
pytest -v                   # Verbose tests
pytest -k "pattern"         # Run matching tests

# Coverage
pytest --cov=src            # Basic coverage
pytest --cov-report=html    # HTML report
open htmlcov/index.html     # View report

# Cleanup
make clean-venv             # Remove venv
deactivate                  # Deactivate venv

# Info
make venv-info              # Show venv details
make help                   # Show all commands
```

---

## Support

For issues or questions:
- **Makefile Reference:** `make help`
- **pytest Docs:** https://docs.pytest.org/
- **uv Docs:** https://github.com/astral-sh/uv
