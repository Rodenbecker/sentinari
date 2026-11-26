"""Provider-agnostic LLM gateway for Sentinari.

Zero-cloud doctrine (§41, reaffirmed §45): the runtime is the local Sentinari
ONNX inference server (:8100, Enigma) via the 'sentinari' provider — landed per
§74g/§75 rig-day checklist. Ollama stays as a registry entry for local use; the
former Gemini cloud provider and the generic OpenAI-compatible provider were
REMOVED in §45 — the gateway keeps its provider registry shape so no caller
ever changes when the provider does.

The rest of the app calls ``llm_gateway.chat()`` / ``llm_gateway.embed()``
without knowing (or caring) where the model lives. Switching providers is a
settings change, not a code change — but the firewall (app/llm_firewall.py)
polices which providers are authorized at all.

Provider config lives in ``config/settings.yaml`` under ``llm.provider``:

    llm:
      provider: sentinari          # sentinari (:8100, Enigma) | ollama | http_json_provider
      sentinari:
        base_url: http://127.0.0.1:8100
        chat_model: gemma-onnx
        timeout_seconds: 600
      chat_model: gemma-onnx
      embedding_model: ""          # Enigma is chat-only; embed() returns None honestly
    # ollama:
    #   base_url: http://127.0.0.1:11434
    #   chat_model: gemma4:12B
    #   embedding_model: nomic-embed-text
    # http_json_provider:
    #   base_url: http://127.0.0.1:9000/v1
    #   chat_model: <local model>
    #   api_key_env: <optional, for a local key only>
    # runtime_llm:
    #   client_backend: gateway     # ollama_client | gateway

API keys are read from environment variables only — never hard-coded.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import requests

from .config import get_settings

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.S)
_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.S)


class LLMGatewayError(RuntimeError):
    """Raised when no configured provider can serve the request."""


def _settings_llm() -> dict[str, Any]:
    settings = get_settings()
    llm = settings.get("llm") if isinstance(settings, dict) else {}
    return dict(llm or {})


def _env_key(env_var: str) -> str:
    """Read an API key from environment, project .env, or sentinel/apis directory."""
    value = str(os.environ.get(str(env_var or "")) or "").strip()
    if value:
        return value
    try:
        from .config import get_project_root
        root = get_project_root()

        # In-tree .env first, then parent fallback
        for env_file in (root / ".env", root.parent / ".env"):
            if env_file.exists():
                prefix = f"{env_var}="
                for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if line.startswith(prefix):
                        val = line[len(prefix):].strip().strip('"').strip("'")
                        if val:
                            return val

        # Check dedicated key files in sentinel/apis/ and app/apis/
        apis_dir = root / "sentinel" / "apis"
        if env_var.upper() in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            gemini_file = apis_dir / "gemini_api.md"
            if gemini_file.exists():
                raw = gemini_file.read_text(encoding="utf-8", errors="replace").strip()
                if raw and not raw.startswith("#"):
                    return raw
    except Exception:
        pass
    return ""


class OllamaProvider:
    """Local Ollama server (current default)."""

    name = "ollama"

    def __init__(self, config: dict[str, Any]) -> None:
        self.base_url = str(config.get("base_url") or "http://127.0.0.1:11434").rstrip("/")
        self.chat_model = str(config.get("chat_model") or "")
        self.embedding_model = str(config.get("embedding_model") or "")
        self.timeout = max(10, int(config.get("chat_timeout_seconds") or 120))

    def is_available(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.1, max_tokens: int = 768) -> str:
        resp = requests.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.chat_model,
                "messages": messages,
                "stream": False,
                "think": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            },
            timeout=self.timeout,
        )
        if resp.status_code == 400 and "think" in str(resp.text or "").lower():
            resp = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.chat_model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": temperature, "num_predict": max_tokens},
                },
                timeout=self.timeout,
            )
        resp.raise_for_status()
        data = resp.json() or {}
        return str((data.get("message") or {}).get("content") or "").strip()

    def embed(self, text: str) -> list[float] | None:
        if not self.embedding_model:
            return None
        try:
            resp = requests.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.embedding_model, "prompt": str(text or "")[:8000]},
                timeout=30,
            )
            resp.raise_for_status()
            embedding = (resp.json() or {}).get("embedding")
            return list(embedding) if isinstance(embedding, list) else None
        except Exception:
            return None


class HTTPJSONProvider:
    """Any local HTTP JSON endpoint speaking the OpenAI chat wire format.

    Renamed from openai_compatible (§45): the name described a wire format,
    not a vendor. Use it only for endpoints on this machine or the LAN —
    the zero-cloud doctrine forbids pointing it at a cloud vendor.
    """

    name = "http_json_provider"

    def __init__(self, config: dict[str, Any]) -> None:
        compatible = dict(config.get("http_json_provider") or {})
        self.base_url = str(compatible.get("base_url") or "").rstrip("/")
        self.api_key = _env_key(str(compatible.get("api_key_env") or ""))
        self.chat_model = str(compatible.get("chat_model") or config.get("chat_model") or "")
        self.embedding_model = str(compatible.get("embedding_model") or "")
        self.timeout = max(10, int(config.get("chat_timeout_seconds") or 120))

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def is_available(self) -> bool:
        return bool(self.base_url and self.chat_model)

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.1, max_tokens: int = 768) -> str:
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json={
                "model": self.chat_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json() or {}
        choices = data.get("choices") or []
        if not choices:
            return ""
        return str((choices[0].get("message") or {}).get("content") or "").strip()

    def embed(self, text: str) -> list[float] | None:
        if not self.base_url or not self.embedding_model:
            return None
        try:
            resp = requests.post(
                f"{self.base_url}/embeddings",
                headers=self._headers(),
                json={"model": self.embedding_model, "input": str(text or "")[:8000]},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json() or {}
            embedding = ((data.get("data") or [{}])[0]).get("embedding")
            return [float(v) for v in embedding] if isinstance(embedding, list) else None
        except Exception:
            return None


class SentinariProvider:
    """Local Sentinari ONNX inference server (:8100) — Enigma, in-house.

    The §74g rig-day provider: speaks POST /api/inference/chat
    ({messages} -> {reply, degraded}) — the wire recorded live in the log.
    Loopback-only by design (inference_settings.yaml binds 127.0.0.1).

    §58 honesty law: is_available() is TRUE only when the engine is
    actually LOADED. A degraded stub reply must never be mistaken for
    model output, so chat() refuses one even in the race where the
    engine dies mid-request (degraded flag checked on every reply).
    """

    name = "sentinari"

    def __init__(self, config: dict[str, Any]) -> None:
        sentinari = dict(config.get("sentinari") or {})
        self.base_url = str(sentinari.get("base_url") or "http://127.0.0.1:8100").rstrip("/")
        self.chat_model = str(sentinari.get("chat_model") or config.get("chat_model") or "gemma-onnx")
        self.embedding_model = ""  # chat-only engine; embed() returns None honestly
        # int4 12B on GPU is quick, on CPU it is not — default generous.
        self.timeout = max(10, int(sentinari.get("timeout_seconds") or config.get("chat_timeout_seconds") or 600))
        self.domain = str(sentinari.get("domain") or "").strip()

    def is_available(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/api/inference/status", timeout=3)
            if resp.status_code != 200:
                return False
            data = resp.json() or {}
            engine = data.get("engine") or {}
            return (not data.get("degraded")) and str(engine.get("status") or "") == "loaded"
        except Exception:
            return False

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.1, max_tokens: int = 768) -> str:
        payload: dict[str, Any] = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.domain:
            payload["domain"] = self.domain
        resp = requests.post(f"{self.base_url}/api/inference/chat", json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json() or {}
        if data.get("degraded"):
            raise LLMGatewayError(
                f"Sentinari inference server is degraded ({data.get('model') or 'no engine loaded'}) — "
                "refusing to treat a stub reply as model output."
            )
        return str(data.get("reply") or "").strip()

    def embed(self, text: str) -> list[float] | None:
        # Enigma serves chat only; the app treats None as "no embedding source"
        # (chunks always persist either way — §7). The embedding story is a
        # separate decision, not a silent stub.
        return None


class GeminiProvider:
    """Google Gemini API provider (cloud / Vertex AI compatible)."""

    name = "gemini"

    def __init__(self, config: dict[str, Any]) -> None:
        gemini = dict(config.get("gemini") or {})
        self.api_key = _env_key(str(gemini.get("api_key_env") or "GEMINI_API_KEY"))
        self.chat_model = str(
            gemini.get("chat_model")
            or config.get("chat_model")
            or "gemini-2.5-flash"
        )
        self.chat_fallback_models = [
            str(m).strip()
            for m in (gemini.get("fallback_chat_models") or ["gemini-flash-latest", "gemini-1.5-flash"])
            if str(m).strip()
        ]
        # outputDimensionality = 768 matches Sentinari's 768-d vector schema exactly!
        self.embedding_model = str(gemini.get("embedding_model") or "text-embedding-004")
        self.embedding_dims = int(gemini.get("embedding_dimensions") or 768)
        self.timeout = max(10, int(config.get("chat_timeout_seconds") or 120))
        self.base = "https://generativelanguage.googleapis.com/v1beta"

    def is_available(self) -> bool:
        return bool(self.api_key)

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.1, max_tokens: int = 768) -> str:
        import time as _time

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                return self._chat_once(messages, temperature=temperature, max_tokens=max_tokens)
            except requests.HTTPError as ex:
                status = getattr(ex.response, "status_code", 0)
                if status not in (429, 500, 503, 504) or attempt == 2:
                    raise
                last_error = ex
                _time.sleep(2.0 * (attempt + 1))
        if last_error is not None:
            raise last_error
        raise LLMGatewayError("Gemini chat failed after retries.")

    def _gemini_post(self, path: str, payload: dict[str, Any], timeout: int) -> requests.Response:
        return requests.post(
            f"{self.base}{path}",
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )

    def _chat_once(self, messages: list[dict[str, str]], *, temperature: float, max_tokens: int) -> str:
        system_text = "\n".join(
            str(m.get("content") or "") for m in messages if str(m.get("role") or "") == "system"
        ).strip()
        contents = []
        for message in messages:
            role = str(message.get("role") or "user")
            content = str(message.get("content") or "").strip()
            if not content or role == "system":
                continue
            contents.append(
                {
                    "role": "model" if role == "assistant" else "user",
                    "parts": [{"text": content}],
                }
            )
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}
        last_error: Exception | None = None
        for model in [self.chat_model, *self.chat_fallback_models]:
            resp = self._gemini_post(f"/models/{model}:generateContent", payload, self.timeout)
            if resp.status_code in (429, 500, 502, 503, 504):
                last_error = requests.HTTPError(f"{model}: {resp.status_code}", response=resp)
                continue
            resp.raise_for_status()
            data = resp.json() or {}
            candidates = data.get("candidates") or []
            if not candidates:
                last_error = LLMGatewayError(f"{model}: empty candidates")
                continue
            parts = (candidates[0].get("content") or {}).get("parts") or []
            return " ".join(str(part.get("text") or "") for part in parts).strip()
        if last_error is not None:
            raise last_error
        raise LLMGatewayError("Gemini chat returned no usable response.")

    def embed(self, text: str) -> list[float] | None:
        if not self.api_key or not self.embedding_model:
            return None
        try:
            payload: dict[str, Any] = {
                "content": {"parts": [{"text": str(text or "")[:8000]}]}
            }
            if self.embedding_dims:
                payload["outputDimensionality"] = self.embedding_dims
            resp = self._gemini_post(
                f"/models/{self.embedding_model}:embedContent", payload, 30
            )
            resp.raise_for_status()
            values = ((resp.json() or {}).get("embedding") or {}).get("values")
            return [float(v) for v in values] if isinstance(values, list) else None
        except Exception:
            return None


class OpenAICompatibleProvider:
    """Any OpenAI-compatible cloud or endpoint (vLLM on GCP, Groq, Vertex AI, etc.)."""

    name = "openai_compatible"

    def __init__(self, config: dict[str, Any]) -> None:
        compatible = dict(config.get("openai_compatible") or config.get("http_json_provider") or {})
        self.base_url = str(compatible.get("base_url") or "").rstrip("/")
        self.embedding_base_url = str(
            compatible.get("embedding_base_url") or self.base_url
        ).rstrip("/")
        self.api_key = _env_key(str(compatible.get("api_key_env") or "OPENAI_API_KEY"))
        self.chat_model = str(compatible.get("chat_model") or config.get("chat_model") or "")
        self.embedding_model = str(compatible.get("embedding_model") or "")
        self.timeout = max(10, int(config.get("chat_timeout_seconds") or 120))

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def is_available(self) -> bool:
        return bool(self.base_url and self.chat_model)

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.1, max_tokens: int = 768) -> str:
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json={
                "model": self.chat_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json() or {}
        choices = data.get("choices") or []
        if not choices:
            return ""
        return str((choices[0].get("message") or {}).get("content") or "").strip()

    def embed(self, text: str) -> list[float] | None:
        if not self.embedding_base_url or not self.embedding_model:
            return None
        try:
            resp = requests.post(
                f"{self.embedding_base_url}/embeddings",
                headers=self._headers(),
                json={"model": self.embedding_model, "input": str(text or "")[:8000]},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json() or {}
            embedding = ((data.get("data") or [{}])[0]).get("embedding")
            return [float(v) for v in embedding] if isinstance(embedding, list) else None
        except Exception:
            return None


class VertexAIProvider:
    """Google Cloud Vertex AI provider (Enterprise / Project-based)."""

    name = "vertex"

    def __init__(self, config: dict[str, Any]) -> None:
        vertex = dict(config.get("vertex") or {})
        self.project = str(vertex.get("project") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "seninari").strip()
        raw_model = str(
            vertex.get("chat_model")
            or config.get("chat_model")
            or "gemma4:26B"
        ).strip()

        # Recognize Gemma variants and map to the active Vertex AI Model Garden MaaS endpoint
        if "gemma" in raw_model.lower():
            self.chat_model_id = "gemma-4-26b-a4b-it-maas"
            self.location = "global"
            self.chat_model = "gemma4:26B"
        else:
            self.chat_model_id = raw_model
            self.location = str(vertex.get("location") or "us-central1").strip()
            self.chat_model = raw_model

        self.embedding_model = str(vertex.get("embedding_model") or "text-embedding-004")
        self.embedding_dims = int(vertex.get("embedding_dimensions") or 768)
        self.timeout = max(10, int(config.get("chat_timeout_seconds") or 120))
        if self.location == "global":
            self.base = f"https://aiplatform.googleapis.com/v1/projects/{self.project}/locations/global/publishers/google"
        else:
            self.base = f"https://{self.location}-aiplatform.googleapis.com/v1/projects/{self.project}/locations/{self.location}/publishers/google"
        self._cached_token = ""
        self._token_expiry = 0.0

    def _get_token(self, force_refresh: bool = False) -> str:
        import time as _time
        if not force_refresh and self._cached_token and _time.time() < self._token_expiry:
            return self._cached_token
        self._cached_token = ""
        self._token_expiry = 0.0
        token = "" if force_refresh else str(os.environ.get("GOOGLE_OAUTH_TOKEN") or "").strip()
        ttl_seconds = 1500

        # 1. Cloud environment: GCP Metadata server (Cloud Run, GCE, GKE)
        if not token:
            try:
                import urllib.request
                req = urllib.request.Request(
                    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
                    headers={"Metadata-Flavor": "Google"},
                )
                with urllib.request.urlopen(req, timeout=2) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    token = str(data.get("access_token") or "").strip()
                    exp_in = int(data.get("expires_in") or 1500)
                    ttl_seconds = max(60, min(1800, exp_in - 120))
            except Exception:
                pass

        # 2. Python google.auth SDK default credentials
        if not token:
            try:
                import google.auth
                import google.auth.transport.requests
                creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
                creds.refresh(google.auth.transport.requests.Request())
                token = str(creds.token or "").strip()
                ttl_seconds = 1200
            except Exception:
                pass

        # 3. Local CLI fallback (gcloud CLI on developer workstation)
        if not token:
            for cmd in ("gcloud auth application-default print-access-token", "gcloud auth print-access-token"):
                try:
                    import subprocess
                    out = subprocess.check_output(cmd, shell=True, timeout=8).decode().strip()
                    lines = [ln.strip() for ln in out.splitlines() if ln.strip() and not ln.startswith("C:\\") and not ln.startswith("WARNING") and not ln.startswith("ERROR")]
                    if lines and lines[-1].startswith("ya29."):
                        token = lines[-1]
                        ttl_seconds = 900
                        break
                except Exception:
                    continue

        if token:
            self._cached_token = token
            self._token_expiry = _time.time() + ttl_seconds
        return token

    def is_available(self) -> bool:
        return bool(self.project and self._get_token())

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.1, max_tokens: int = 768) -> str:
        token = self._get_token()
        if not token:
            raise LLMGatewayError("Vertex AI: No OAuth access token available.")

        system_text = "\n".join(
            str(m.get("content") or "") for m in messages if str(m.get("role") or "") == "system"
        ).strip()
        contents = []
        for message in messages:
            role = str(message.get("role") or "user")
            content = str(message.get("content") or "").strip()
            if not content or role == "system":
                continue
            contents.append(
                {
                    "role": "model" if role == "assistant" else "user",
                    "parts": [{"text": content}],
                }
            )
        effective_max_tokens = (
            max(int(max_tokens or 768), 2048) if "gemma" in self.chat_model_id.lower() else int(max_tokens or 768)
        )
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": effective_max_tokens,
            },
        }
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}

        primary_url = f"{self.base}/models/{self.chat_model_id}:generateContent"
        fallback_url = f"https://us-central1-aiplatform.googleapis.com/v1/projects/{self.project}/locations/us-central1/publishers/google/models/gemini-2.5-flash:generateContent"
        endpoints = [primary_url]
        if fallback_url != primary_url:
            endpoints.append(fallback_url)

        import time as _time

        last_exc: Exception | None = None
        data: dict[str, Any] = {}
        for url in endpoints:
            for attempt in range(3):
                try:
                    resp = requests.post(
                        url,
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                        json=payload,
                        verify=False,
                        timeout=self.timeout,
                    )
                    if resp.status_code in (401, 403) and attempt < 2:
                        token = self._get_token(force_refresh=True) or token
                        continue
                    if resp.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                        _time.sleep(1.5 * (attempt + 1))
                        continue
                    resp.raise_for_status()
                    data = resp.json() or {}
                    last_exc = None
                    break
                except Exception as ex:
                    last_exc = ex
                    if attempt < 2:
                        _time.sleep(1.5 * (attempt + 1))
                    else:
                        break
            if last_exc is None and data.get("candidates"):
                break
        if last_exc is not None and not data.get("candidates"):
            raise last_exc
        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMGatewayError(f"Vertex AI: empty response from {self.chat_model}")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        non_thought = [str(p.get("text") or "") for p in parts if not p.get("thought") and p.get("text")]
        if non_thought:
            return " ".join(non_thought).strip()
        return " ".join(str(p.get("text") or "") for p in parts).strip()

    def embed(self, text: str) -> list[float] | None:
        res = self.embed_batch([text])
        return res[0] if res else None

    def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        if not texts:
            return []
        token = self._get_token()
        if not token:
            return [None] * len(texts)
        url = f"https://us-central1-aiplatform.googleapis.com/v1/projects/{self.project}/locations/us-central1/publishers/google/models/{self.embedding_model}:predict"
        payload = {
            "instances": [{"content": str(t or "")[:8000], "task_type": "RETRIEVAL_DOCUMENT"} for t in texts],
            "parameters": {"outputDimensionality": self.embedding_dims},
        }
        try:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
                verify=False,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json() or {}
            preds = data.get("predictions") or []
            if len(preds) == len(texts):
                out: list[list[float] | None] = []
                for p in preds:
                    vals = p.get("embeddings", {}).get("values")
                    out.append([float(v) for v in vals] if isinstance(vals, list) else None)
                return out
        except Exception:
            pass
        return [None] * len(texts)


_PROVIDERS: dict[str, type] = {
    "sentinari": SentinariProvider,
    "vertex": VertexAIProvider,
    "ollama": OllamaProvider,
    "gemini": GeminiProvider,
    "openai_compatible": OpenAICompatibleProvider,
    "http_json_provider": HTTPJSONProvider,
}


class LLMGateway:
    """Single entry point: chat() and embed() on any configured provider."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = dict(config) if config else _settings_llm()
        self.provider_name = str(self.config.get("provider") or "ollama").strip().lower()
        provider_cls = _PROVIDERS.get(self.provider_name, OllamaProvider)
        self.provider = provider_cls(self.config)
        self._fallbacks: list[Any] = []
        for fallback_name in self.config.get("fallback_providers") or []:
            fallback_cls = _PROVIDERS.get(str(fallback_name).strip().lower())
            if fallback_cls is not None:
                self._fallbacks.append(fallback_cls(self.config))

    # -- introspection ------------------------------------------------------

    def describe(self) -> dict[str, Any]:
        return {
            "provider": self.provider.name,
            "available": self.provider.is_available(),
            "chat_model": getattr(self.provider, "chat_model", ""),
            "embedding_model": getattr(self.provider, "embedding_model", ""),
            "provider_cut_from_ollama": self.provider.name != "ollama",
        }

    # -- core operations ----------------------------------------------------

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.1, max_tokens: int = 768) -> str:
        attempts: list[Any] = [self.provider, *self._fallbacks]
        last_error: Exception | None = None
        for provider in attempts:
            if not provider.is_available():
                continue
            try:
                return provider.chat(messages, temperature=temperature, max_tokens=max_tokens)
            except Exception as ex:  # try the next provider
                last_error = ex
        if last_error is not None:
            raise LLMGatewayError(f"All LLM providers failed; last error: {last_error}")
        raise LLMGatewayError(
            f"No LLM provider available (configured: {self.provider.name}). "
            "Check the provider settings and API keys."
        )

    def embed(self, text: str) -> list[float] | None:
        import math as _math

        for provider in [self.provider, *self._fallbacks]:
            embedding = provider.embed(text)
            if embedding:
                norm = _math.sqrt(sum(float(x) * float(x) for x in embedding))
                if norm > 0:
                    return [float(x) / norm for x in embedding]
                return [float(x) for x in embedding]
        return None

    def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        import math as _math

        if not texts:
            return []
        for provider in [self.provider, *self._fallbacks]:
            if hasattr(provider, "embed_batch"):
                raw_batch = provider.embed_batch(texts)
                if raw_batch and any(raw_batch):
                    out: list[list[float] | None] = []
                    for emb in raw_batch:
                        if emb:
                            norm = _math.sqrt(sum(float(x) * float(x) for x in emb))
                            out.append([float(x) / norm for x in emb] if norm > 0 else [float(x) for x in emb])
                        else:
                            out.append(None)
                    return out
            else:
                out_single = [self.embed(t) for t in texts]
                if any(out_single):
                    return out_single
        return [None] * len(texts)

    # -- structured output --------------------------------------------------

    def chat_json(self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int = 1024) -> Any:
        """Chat and parse a JSON object/array out of the reply."""
        raw = self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        return parse_json_loose(raw)


def parse_json_loose(raw: str) -> Any:
    """Extract JSON from a model reply that may include prose or fences."""
    text = str(raw or "").strip()
    if not text:
        raise LLMGatewayError("Model returned an empty reply.")
    if "```" in text:
        fenced = re.findall(r"```(?:json)?\s*(.*?)```", text, re.S)
        if fenced:
            text = fenced[0].strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    match = _JSON_OBJECT_RE.search(text) or _JSON_ARRAY_RE.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass
    raise LLMGatewayError("Model reply did not contain parseable JSON.")


_gateway: LLMGateway | None = None


def get_gateway() -> LLMGateway:
    """Process-wide gateway instance (re-reads settings on first use)."""
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway


def reset_gateway() -> None:
    """Force the next get_gateway() to reload settings (used after config edits)."""
    global _gateway
    _gateway = None


class GatewayBackedClient:
    """Drop-in replacement for OllamaClient, backed by the provider gateway.

    Implements the exact client surface the app consumes — chat(), embed(),
    is_available(), list_models(), get_runtime_diagnostics() — so callers
    (conversation, ingestion, playground, session_memory) need no changes
    when Sentinari's LLM moves to a different local provider.

    The diagnostics payload keeps the Ollama-runtime shape (the UI renders
    it) but honestly reports the gateway's real provider and models.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._gateway = LLMGateway(config)
        self.provider_name = self._gateway.provider_name
        self.chat_model = str(getattr(self._gateway.provider, "chat_model", "") or "")
        self.embedding_model = str(getattr(self._gateway.provider, "embedding_model", "") or "")
        self.base_url = str(getattr(self._gateway.provider, "base_url", "") or getattr(self._gateway.provider, "base", "") or "")
        self.temperature = float(self._gateway.config.get("temperature") or 0.1)
        self.max_output_tokens = int(self._gateway.config.get("max_output_tokens") or 768)
        self.num_ctx = int(self._gateway.config.get("num_ctx") or 8192)

    # -- capability ----------------------------------------------------------

    def is_available(self) -> bool:
        try:
            return bool(self._gateway.provider.is_available())
        except Exception:
            return False

    def list_models(self) -> list[str]:
        provider = self._gateway.provider
        models = [self.chat_model]
        models.extend(getattr(provider, "chat_fallback_models", []) or [])
        if self.embedding_model:
            models.append(self.embedding_model)
        seen: set[str] = set()
        return [m for m in models if m and not (m in seen or seen.add(m))]

    # -- core operations -------------------------------------------------

    def chat(self, messages: list[dict[str, str]], *, num_ctx: int | None = None) -> str:
        # num_ctx is an Ollama-specific window hint; other providers manage
        # their own context. Temperature/max tokens come from settings.
        return self._gateway.chat(
            messages,
            temperature=self.temperature,
            max_tokens=self.max_output_tokens,
        )

    def embed(self, text: str) -> list[float] | None:
        return self._gateway.embed(text)

    def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        return self._gateway.embed_batch(texts)

    # -- diagnostics -----------------------------------------------------

    def get_runtime_diagnostics(self, *, probe: bool = True) -> dict[str, Any]:
        describe = self._gateway.describe()
        return {
            "base_url": self.base_url or f"gateway:{self.provider_name}",
            "reachable": bool(describe.get("available")),
            "ready": bool(describe.get("available")),
            "requires_attention": not bool(describe.get("available")),
            "chat_model": self.chat_model,
            "embedding_model": self.embedding_model,
            "available_models": self.list_models(),
            "chat_model_present": bool(self.chat_model),
            "embedding_model_present": bool(self.embedding_model),
            "chat_capabilities": ["chat"],
            "embedding_capabilities": ["embedding"] if self.embedding_model else [],
            "chat_transport": f"gateway:{self.provider_name}",
            "warnings": [],
            "operator_trigger": "",
            "provider": self.provider_name,
            "gateway_provider_cut_from_ollama": self.provider_name != "ollama",
        }
