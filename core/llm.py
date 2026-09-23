"""One small LLM client, three free providers, no vendor SDK.

Default is Groq: their terms say inputs and outputs are not used to train
models, and Zero Data Retention can be switched on per account in Data
Controls. Cloudflare Workers AI is the fallback with a free daily allowance,
and Ollama is there for fully local runs.

Everything sent from this module has already been through core.privacy.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests

from . import config

TIMEOUT = 90
MAX_ATTEMPTS = 3


class LLMError(RuntimeError):
    pass


class QuotaExceeded(LLMError):
    pass


@dataclass
class LLMResponse:
    text: str
    tokens: int = 0
    model: str = ""


Reporter = Callable[[str, int], None]  # (kind, tokens) -> None


class LLM:
    """Thin chat wrapper. ``on_usage`` is called once per successful request."""

    def __init__(self, provider: str | None = None, model: str | None = None,
                 on_usage: Reporter | None = None):
        self.provider = (provider or config.llm_provider()).lower()
        self.model = model or config.llm_model()
        self.on_usage = on_usage

    # ------------------------------------------------------------------
    def available(self) -> bool:
        if self.provider == "groq":
            return bool(config.groq_api_key())
        if self.provider == "cloudflare":
            return bool(config.cf_account_id() and config.cf_api_token())
        if self.provider == "ollama":
            return True
        return False

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.2,
             max_tokens: int = 2000, json_mode: bool = False) -> LLMResponse:
        if not self.available():
            raise LLMError(
                f"No credentials for provider '{self.provider}'. "
                "Add the key in Streamlit secrets (see README)."
            )
        last_error: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self._dispatch(messages, temperature, max_tokens, json_mode)
                if self.on_usage:
                    self.on_usage("llm", response.tokens)
                return response
            except QuotaExceeded:
                raise
            except LLMError as exc:
                last_error = exc
                if attempt == MAX_ATTEMPTS - 1:
                    break
                time.sleep(2 ** attempt)
        raise LLMError(str(last_error))

    def ask(self, system: str, user: str, **kwargs: Any) -> str:
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
        return self.chat(messages, **kwargs).text

    def ask_json(self, system: str, user: str, **kwargs: Any) -> Any:
        """Ask for JSON and parse it, tolerating fences and stray prose."""
        kwargs.setdefault("json_mode", True)
        raw = self.ask(system, user, **kwargs)
        return parse_json(raw)

    # ------------------------------------------------------------------
    def _dispatch(self, messages, temperature, max_tokens, json_mode) -> LLMResponse:
        if self.provider == "groq":
            return self._groq(messages, temperature, max_tokens, json_mode)
        if self.provider == "cloudflare":
            return self._cloudflare(messages, temperature, max_tokens)
        if self.provider == "ollama":
            return self._ollama(messages, temperature, json_mode)
        raise LLMError(f"Unknown provider '{self.provider}'")

    def _groq(self, messages, temperature, max_tokens, json_mode) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if "gpt-oss" in self.model:
            # gpt-oss thinks before it answers and the thinking counts against
            # max_tokens. Left on "high" a short budget is spent reasoning and
            # the reply comes back empty.
            payload["reasoning_effort"] = config.get("GROQ_REASONING_EFFORT", "low")
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {config.groq_api_key()}",
                     "Content-Type": "application/json"},
            json=payload,
            timeout=TIMEOUT,
        )
        self._raise_for_status(response)
        body = response.json()
        usage = body.get("usage") or {}
        return LLMResponse(
            text=body["choices"][0]["message"]["content"] or "",
            tokens=int(usage.get("total_tokens") or 0),
            model=self.model,
        )

    def _cloudflare(self, messages, temperature, max_tokens) -> LLMResponse:
        url = (f"https://api.cloudflare.com/client/v4/accounts/"
               f"{config.cf_account_id()}/ai/run/{self.model}")
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {config.cf_api_token()}"},
            json={"messages": messages, "temperature": temperature,
                  "max_tokens": max_tokens},
            timeout=TIMEOUT,
        )
        self._raise_for_status(response)
        body = response.json()
        result = body.get("result") or {}
        return LLMResponse(text=result.get("response", ""), model=self.model)

    def _ollama(self, messages, temperature, json_mode) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if json_mode:
            payload["format"] = "json"
        response = requests.post(f"{config.ollama_host()}/api/chat",
                                 json=payload, timeout=TIMEOUT * 4)
        self._raise_for_status(response)
        body = response.json()
        return LLMResponse(text=(body.get("message") or {}).get("content", ""),
                           model=self.model)

    @staticmethod
    def _raise_for_status(response: requests.Response) -> None:
        if response.status_code == 429:
            retry = response.headers.get("retry-after")
            raise QuotaExceeded(
                "The shared free-tier key is rate limited right now"
                + (f" (retry in {retry}s)." if retry else ".")
                + " Wait a minute and try again."
            )
        if response.status_code >= 400:
            detail = response.text[:300]
            raise LLMError(f"{response.status_code} from provider: {detail}")


# ---------------------------------------------------------------- helpers
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_json(raw: str) -> Any:
    """Best-effort JSON parse of a model reply."""
    if not raw:
        raise LLMError("Empty reply from the model")
    text = raw.strip()
    fenced = _FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost {...} or [...] in the reply.
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError("The model did not return usable JSON")
