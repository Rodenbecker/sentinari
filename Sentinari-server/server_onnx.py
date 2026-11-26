"""Sentinari Inference Server — Local Gemma 4 26B GGUF Bridge (RTX 5070 Ti)."""

from __future__ import annotations

import argparse
import json
import sqlite3
import threading
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

SETTINGS_PATH = Path(__file__).resolve().parent / "inference_settings.yaml"
LLAMA_BACKEND_URL = "http://127.0.0.1:8101"
GGUF_MODEL_PATH = r"D:\sentinari\Gemma\gemma-4-26B-A4B-it-qat-q4_0-gguf\gemma-4-26B_q4_0-it.gguf"


def _load_settings() -> dict[str, Any]:
    try:
        import yaml
        data = yaml.safe_load(SETTINGS_PATH.read_text(encoding="utf-8"))
        return dict(data or {})
    except Exception:
        return {}


SETTINGS = _load_settings()
SERVER_CFG = dict(SETTINGS.get("server") or {})
MODEL_CFG = dict(SETTINGS.get("model") or {})
PERSONA_CFG = dict(SETTINGS.get("personality") or {})
DOMAINS_CFG = dict(SETTINGS.get("domains") or {})
LOG_CFG = dict(SETTINGS.get("logging") or {})

HOST = str(SERVER_CFG.get("host") or "127.0.0.1")
PORT = int(SERVER_CFG.get("port") or 8100)
LOG_DB = (Path(__file__).resolve().parent / str(LOG_CFG.get("db_path") or "inference_log.sqlite3")).resolve()


@contextmanager
def log_connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(LOG_DB, timeout=20)
    try:
        conn.execute("PRAGMA busy_timeout = 20000")
        yield conn
        conn.commit()
    finally:
        conn.close()


def _init_log_db() -> None:
    with log_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS inference_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                domain TEXT NOT NULL,
                persona TEXT NOT NULL,
                engine TEXT NOT NULL,
                prompt_chars INTEGER NOT NULL,
                reply_chars INTEGER NOT NULL,
                elapsed_ms INTEGER NOT NULL,
                status TEXT NOT NULL,
                error_text TEXT
            )
            """
        )


def _log_request(**fields: Any) -> None:
    try:
        with log_connection() as conn:
            conn.execute(
                "INSERT INTO inference_log (ts, endpoint, domain, persona, engine,"
                " prompt_chars, reply_chars, elapsed_ms, status, error_text)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                    str(fields.get("endpoint") or "chat"),
                    str(fields.get("domain") or "default"),
                    str(fields.get("persona") or ""),
                    str(fields.get("engine") or ""),
                    int(fields.get("prompt_chars") or 0),
                    int(fields.get("reply_chars") or 0),
                    int(fields.get("elapsed_ms") or 0),
                    str(fields.get("status") or "ok"),
                    fields.get("error_text"),
                ),
            )
    except Exception as ex:
        print(f"[log] WARNING: could not write inference_log row: {ex}")


PERSONA_NAME = str(PERSONA_CFG.get("name") or "Sentinari")
PERSONA_TONE = str(PERSONA_CFG.get("tone") or "Calm, precise, evidence-first; professional warmth without intimacy")
PERSONA_LANGUAGE = str(PERSONA_CFG.get("default_language") or "English")


def resolve_domain(requested: str | None) -> tuple[str, dict[str, Any]]:
    key = str(requested or "").strip().lower() or "default"
    if key in DOMAINS_CFG and isinstance(DOMAINS_CFG[key], dict):
        return key, dict(DOMAINS_CFG[key])
    default_cfg = DOMAINS_CFG.get("default")
    return "default", dict(default_cfg if isinstance(default_cfg, dict) else {})


def build_system_prompt(domain: str, domain_cfg: dict[str, Any]) -> str:
    parts = [
        f"You are {PERSONA_NAME}, the resident intelligence of the Sentinari research platform by Inspirari.",
        f"Tone: {PERSONA_TONE}.",
        f"Language: {PERSONA_LANGUAGE} unless the user writes in another language.",
    ]
    system_text = str(domain_cfg.get("system_prompt") or "").strip()
    if system_text:
        parts.append(system_text)
    focus = domain_cfg.get("focus")
    if focus:
        parts.append(f"Domain focus: {focus}.")
    return "\n".join(part for part in parts if part)


class LocalLlamaBridgeEngine:
    """Connects Sentinari's native inference API to local llama-server on :8101."""

    def __init__(self) -> None:
        self.requested_path = GGUF_MODEL_PATH
        self.loaded_path = GGUF_MODEL_PATH
        self.execution_provider = "cuda (RTX 5070 Ti)"
        self.max_length = int(MODEL_CFG.get("max_length") or 8192)
        self.load_seconds = 0.0
        self.detail = "Connected to local Gemma 4 26B GGUF backend (:8101)"

    def _ping_backend(self) -> bool:
        try:
            req = urllib.request.Request(f"{LLAMA_BACKEND_URL}/health", method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    @property
    def status(self) -> str:
        return "loaded" if self._ping_backend() else "unconfigured"

    def is_loaded(self) -> bool:
        return self._ping_backend()

    def load(self, model_path: str | None = None) -> dict[str, Any]:
        if model_path:
            self.requested_path = str(model_path)
        return self.describe()

    def describe(self) -> dict[str, Any]:
        online = self._ping_backend()
        return {
            "engine": "llama.cpp-cuda-bridge",
            "status": "loaded" if online else "unconfigured",
            "detail": self.detail if online else "Start START_GEMMA4.bat on :8101 first",
            "model_path": self.loaded_path,
            "execution_provider": self.execution_provider,
            "max_length": self.max_length,
            "load_seconds": self.load_seconds,
        }

    def generate_chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
        top_p: float,
    ) -> str:
        payload = json.dumps(
            {
                "model": "gemma-4-26b",
                "messages": messages,
                "max_tokens": int(max_tokens),
                "temperature": float(temperature),
                "top_p": float(top_p),
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{LLAMA_BACKEND_URL}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError("Empty response from local Gemma 4 backend")
        return str((choices[0].get("message") or {}).get("content") or "").strip()


ENGINE = LocalLlamaBridgeEngine()
STARTED_AT = time.time()
COUNTS = {"chat_ok": 0, "chat_error": 0, "stub_replies": 0}
_COUNTS_LOCK = threading.Lock()


def _bump(key: str) -> None:
    with _COUNTS_LOCK:
        COUNTS[key] = COUNTS.get(key, 0) + 1


app = FastAPI(title="Sentinari Inference Server (Gemma 4 26B Local)", version="0.2.0")


class ChatRequest(BaseModel):
    prompt: str | None = None
    messages: list[dict[str, str]] | None = None
    domain: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=8192)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)


def _normalise_messages(request: ChatRequest, system_prompt: str) -> list[dict[str, str]]:
    if request.messages:
        messages = [
            {"role": str(m.get("role") or "user"), "content": str(m.get("content") or "")}
            for m in request.messages
            if str(m.get("content") or "").strip()
        ]
    else:
        messages = [{"role": "user", "content": str(request.prompt or "").strip()}]
    messages = [m for m in messages if m["content"]]
    if not messages:
        raise HTTPException(status_code=400, detail="prompt or messages required")
    messages.insert(0, {"role": "system", "content": system_prompt})
    return messages


@app.get("/health")
def health() -> dict[str, Any]:
    online = ENGINE.is_loaded()
    return {
        "ok": True,
        "service": "sentinari-inference",
        "engine_status": "loaded" if online else "unconfigured",
        "degraded": not online,
        "uptime_seconds": int(time.time() - STARTED_AT),
    }


@app.get("/api/inference/status")
def inference_status() -> dict[str, Any]:
    online = ENGINE.is_loaded()
    return {
        "ok": True,
        "service": "sentinari-inference",
        "version": app.version,
        "uptime_seconds": int(time.time() - STARTED_AT),
        "engine": ENGINE.describe(),
        "degraded": not online,
        "persona": {"name": PERSONA_NAME, "tone": PERSONA_TONE, "language": PERSONA_LANGUAGE},
        "domains": sorted(DOMAINS_CFG.keys()) if DOMAINS_CFG else ["default"],
        "counts": dict(COUNTS),
        "log_db": LOG_DB.name,
    }


@app.get("/api/inference/domains")
def inference_domains() -> dict[str, Any]:
    return {
        "ok": True,
        "default": "default",
        "domains": [
            {"domain": name, "focus": cfg.get("focus"), "temperature": cfg.get("temperature")}
            for name, cfg in sorted(DOMAINS_CFG.items())
            if isinstance(cfg, dict)
        ],
    }


@app.post("/api/inference/chat")
def inference_chat(request: ChatRequest) -> dict[str, Any]:
    started = time.time()
    domain, domain_cfg = resolve_domain(request.domain)
	
system_prompt = build_system_prompt(domain, domain_cfg)
try:
messages = _normalise_messages(request, system_prompt)
except HTTPException:
_bump("chat_error")
raise
temperature = float(
request.temperature
if request.temperature is not None
else (domain_cfg.get("temperature") if domain_cfg.get("temperature") is not None else 0.1)
)
max_tokens = int(request.max_tokens or domain_cfg.get("max_tokens") or 768)
top_p = float(request.top_p if request.top_p is not None else (domain_cfg.get("top_p") or 0.9))
prompt_chars = sum(len(m["content"]) for m in messages)
try:
if ENGINE.is_loaded():
reply = ENGINE.generate_chat(
messages,
max_tokens=max_tokens,
temperature=temperature,
top_p=top_p,
)
engine_label = "gemma-4-26b:cuda"
else:
reply = (
"[Sentinari inference: local Gemma 4 backend (:8101) not started yet. "
"Please double-click D:\sentinari\START_GEMMA4.bat first.]"
)
engine_label = "degraded-stub"
_bump("stub_replies")
elapsed_ms = int((time.time() - started) * 1000)
_bump("chat_ok")
_log_request(
endpoint="chat",
domain=domain,
persona=PERSONA_NAME,
engine=engine_label,
prompt_chars=prompt_chars,
reply_chars=len(reply),
elapsed_ms=elapsed_ms,
status="ok",
)
return {
"ok": True,
"reply": reply,
"domain": domain,
"persona": PERSONA_NAME,
"model": "gemma-4-26b-q4_0-local",
"degraded": not ENGINE.is_loaded(),
"elapsed_ms": elapsed_ms,
}
except HTTPException:
raise
except Exception as ex:
elapsed_ms = int((time.time() - started) * 1000)
_bump("chat_error")
_log_request(
endpoint="chat",
domain=domain,
persona=PERSONA_NAME,
engine=ENGINE.status,
prompt_chars=prompt_chars,
reply_chars=0,
elapsed_ms=elapsed_ms,
status="error",
error_text=str(ex)[:500],
)
raise HTTPException(status_code=503, detail=f"inference failed: {ex}") from ex
@app.post("/api/inference/model/load")
def inference_model_load(payload: dict[str, Any] | None = None) -> dict[str, Any]:
path = str((payload or {}).get("path") or "")
result = ENGINE.load(path or None)
return {"ok": ENGINE.is_loaded(), "engine": result}
@app.get("/api/inference/log")
def inference_log(limit: int = 20) -> dict[str, Any]:
limit = max(1, min(int(limit or 20), 200))
with log_connection() as conn:
rows = conn.execute(
"SELECT id, ts, endpoint, domain, persona, engine, prompt_chars,"
" reply_chars, elapsed_ms, status, error_text"
f" FROM inference_log ORDER BY id DESC LIMIT {limit}"
).fetchall()
keys = [
"id", "ts", "endpoint", "domain", "persona", "engine",
"prompt_chars", "reply_chars", "elapsed_ms", "status", "error_text",
]
return {"ok": True, "rows": [dict(zip(keys, row)) for row in rows]}
def main() -> None:
parser = argparse.ArgumentParser(description="Sentinari Gemma 4 26B inference bridge")
parser.add_argument("--host", default=HOST)
parser.add_argument("--port", type=int, default=PORT)
parser.add_argument("--model", default=None)
args = parser.parse_args()
_init_log_db()
print(f"[sentinari-inference] bridge status: {ENGINE.status} ({ENGINE.detail})")
print(f"[sentinari-inference] listening on http://{args.host}:{args.port}")
uvicorn.run(app, host=args.host, port=args.port, log_level="info")
if name == "main":
main()

