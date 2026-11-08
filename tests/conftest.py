import pytest

from src.logging_utils import configure_logging


@pytest.fixture(autouse=True)
def log_to_a_temporary_file(tmp_path, monkeypatch):
    """Keep test runs out of the real logs/ folder. Tests can read the file at tmp_path/test.log."""
    path = tmp_path / "test.log"
    monkeypatch.setenv("VIBEMATCH_LOG_FILE", str(path))
    monkeypatch.setenv("VIBEMATCH_EVAL_LOG_FILE", str(tmp_path / "eval.log"))
    configure_logging(path)
    yield path
