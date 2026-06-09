"""pytest bootstrap: make the `app` package importable and register markers.

Lives at project root so `import app.gap` etc. resolve no matter where pytest runs.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: needs the local DB up and the mpnet model on disk (slow). "
        "Run with `pytest -m integration`; skipped automatically if unavailable.",
    )
