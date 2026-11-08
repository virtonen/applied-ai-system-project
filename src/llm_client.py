"""
A tiny Gemini client that uses only the standard library (no extra package to install).

The API key comes from the GEMINI_API_KEY environment variable or a local .env file (which is
gitignored). The key is sent in a request header, never put in a URL, and never logged.
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

MODEL = "gemini-flash-lite-latest"  # the same model the DocuBot project used
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class LLMError(Exception):
    """The model could not be reached or gave no usable reply."""


def load_dotenv(path: Optional[Path] = None) -> None:
    """Read KEY=VALUE lines from a .env file into the environment (existing variables win)."""
    try:
        lines = (path or ENV_FILE).read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


class GeminiClient:
    def __init__(self, api_key: str, model: str = MODEL, timeout: float = 20.0):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def generate(self, prompt: str, max_tokens: int = 300) -> str:
        """Send one prompt and return the reply text. Raises LLMError with a safe message."""
        body = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens},
        }).encode("utf-8")
        request = urllib.request.Request(
            ENDPOINT.format(model=self.model),
            data=body,
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.load(response)
        except urllib.error.HTTPError as error:
            raise LLMError(f"Gemini returned HTTP {error.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise LLMError(f"could not reach Gemini ({type(error).__name__})") from None
        except json.JSONDecodeError:
            raise LLMError("Gemini sent a reply that was not JSON") from None

        try:
            text = "".join(part.get("text", "") for part in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError, TypeError):
            raise LLMError("Gemini sent no usable text (the reply may have been blocked)") from None
        if not text.strip():
            raise LLMError("Gemini sent an empty reply")
        return text.strip()


def make_client() -> Optional[GeminiClient]:
    """A client if an API key is available, otherwise None."""
    load_dotenv()
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    return GeminiClient(key) if key else None
