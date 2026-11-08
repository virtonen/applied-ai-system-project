import pytest

from src import explain, llm_client
from src.logging_utils import configure_logging


@pytest.fixture(autouse=True)
def log_to_a_temporary_file(tmp_path, monkeypatch):
    """Keep test runs out of the real logs/ folder. Tests can read the file at tmp_path/test.log."""
    path = tmp_path / "test.log"
    monkeypatch.setenv("VIBEMATCH_LOG_FILE", str(path))
    monkeypatch.setenv("VIBEMATCH_EVAL_LOG_FILE", str(tmp_path / "eval.log"))
    configure_logging(path)
    yield path


@pytest.fixture(autouse=True)
def no_real_api_key(tmp_path, monkeypatch):
    """Tests never find the real API key, so they can never make a live call by accident."""
    monkeypatch.setattr(llm_client, "ENV_FILE", tmp_path / "no.env")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    explain.clear_cache()
    yield
    explain.clear_cache()
