from __future__ import annotations
# marker

import json
import os
import secrets
import sys
import re
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .auto_ingest import AutoIngestService
from .chat_uploads import allocate_chat_upload_path, sanitize_chat_upload_filename
from .coding_corpus import get_coding_corpus_progress, sync_coding_corpus
from .config import (
    clamp_behavior_variant,
    clamp_temperature,
    clamp_top_k,
    ensure_protected_dirs,
    get_config_path,
    get_settings,
    get_project_root,
    load_raw_settings,
    reload_settings,
    save_raw_settings,
)
from .conversation import run_chat
from .db import get_connection, get_read_connection, initialize_database
from .skills_store import (
    get_skills_root,
    is_fallback_disabled,
    load_skill_index,
    register_skill,
    sanitize_skill_name,
    set_fallback_enabled,
)
from .ingestion import build_ollama_client, ingest_files, ingest_url
from .llm_boundary import build_ollama_boundary_runtime, is_ollama_runtime_probe_disabled
from .escalation_queue import (
    get_escalation_queue_settings,
    get_escalation_queue_runtime_status,
    list_escalations,
    submit_escalation,
)
from . import assessment_pipeline
from . import victus as victus_module
from .models import (
    AdminLoginRequest,
    ChatRequest,
    AssessmentRunRequest,
    DirectChatRequest,
    EscalationQueryRequest,
    IngestFilesRequest,
    IntakeApproveRequest,
    IngestUrlRequest,
    ModelLabRunRequest,
    OpenAlexToggleRequest,
    ScoutBlockRequest,
    ScoutRequest,
    SourceAssessRequest,
    PlaygroundChatRequest,
    PlaygroundQualiaBenchmarkRequest,
    QualiaRecommendationRequest,
    PlaygroundQualiaSimulationRequest,
    ForensicAuditRequest,
    PlaygroundVideoPlanRequest,
    PlaygroundVideoRenderRequest,
    PlaygroundVideoStitchRequest,
    PlaygroundVideoWanRequest,
    PersonalityUpdateRequest,
    SafetyUpdateRequest,
    SearchRequest,
    ShellRunRequest,
    TaskCreateRequest,
    TaskUpdateRequest,
    TaxonomyConfigureRequest,
    UnsupervisedRebuildRequest,
)
from .operator_control import (
    build_task_prompt,
    create_task,
    ensure_live_operator_state,
    get_task,
    get_live_operator_state,
    list_profile_snapshots,
    list_qualia_history,
    list_tasks,
    record_qualia_history,
    snapshot_profile_settings,
    upsert_live_operator_state,
    update_task,
    update_task_attachments,
    update_task_feedback,
)
from .output_sanitizer import sanitize_user_facing_text
from .personal_growth import (
    create_personal_growth_finetune_dataset,
    initialize_personal_growth_database,
    ingest_personal_growth_file,
    is_personal_growth_media_file,
    personal_growth_finetune_status,
    personal_growth_status,
    register_personal_growth_media,
    record_personal_growth_failure,
)
from .llm_firewall import evaluate_runtime_llm_policy
from .ollama_client import OllamaClient
from .playground import (
    _score_playground_response,  # noqa: F401  (§51 model-lab heuristic scorer)
    get_learning_library_progress,
    get_playground_config,
    run_qualia_benchmark,
    run_qualia_simulation,
    run_autonomous_chat,
)
from .qualia_recommendation import build_qualia_recommendation
from .forensic_governance import (
    generate_merciless_audit_report,
    persist_forensic_audit,
    list_forensic_audits,
    get_forensic_audit_by_ref,
    render_standalone_audit_html,
    EXEMPLARS,
)
from .retrieval import search_chunks
from .skill_review import router as skill_review_router
from .security import (
    create_admin_session_token,
    get_admin_auth_settings,
    parse_basic_auth_header,
    validate_admin_session_token,
    verify_admin_credentials,
)
from .session_memory import get_session_history_readonly
from .shell_policy import (
    append_shell_audit_event,
    ensure_shell_policy_dirs,
    evaluate_shell_request,
    get_public_shell_policy,
    get_shell_policy,
    reset_workflow_state,
)
from .sentinel_domains import (
    ensure_sentinel_database,
    get_sentinel_status,
    ingest_github_dataset_to_field,
    ingest_huggingface_dataset_to_field,
    ingest_sentinel_field_files,
    list_github_dataset_files,
    remove_sentinel_field_data,
)

# Sentinel upload policy: no more than 100 files per upload; PDFs max 30 MB,
# all other document types max 80 MB. GitHub dataset pulls: up to 1000 files
# per repo.
SENTINEL_MAX_UPLOAD_FILES = 100
SENTINEL_PDF_MAX_MB = 30
SENTINEL_DOC_MAX_MB = 80
SENTINEL_GITHUB_MAX_FILES = 1000
from .taxonomy import configure_taxonomy, ensure_configured_taxonomy_dirs, list_taxonomy
from .unsupervised import (
    list_cluster_members,
    list_unsupervised_clusters,
    list_unsupervised_runs,
    rebuild_unsupervised_clusters,
)
from .video_lab import (
    build_plan_from_prompt,
    get_video_lab_status,
    get_wan_video_status,
    render_stitched_images,
    render_text_plan,
    render_wan_text_video,
    resolve_output_file,
)
from .video_jobs import create_video_job, get_video_job, list_video_jobs, update_video_job


_settings = get_settings()
_OPENALEX_MANIFEST_PATH = get_project_root() / "data" / "source_manifests" / "sentinari_source_manifest.json"
_RUNTIME_MODE_STUDIO = "studio"
_RUNTIME_MODE_RUNTIME = "runtime"
_RUNTIME_COMPUTE_ALLOWED_PATHS = {
    "/health",
    "/api/runtime/profile",
}
_INTERACTIVE_ADMIN_AUTH_PATHS = {
    "/api/chat",
    "/api/chat/upload",
    "/api/chat/history",
    "/api/search",
    "/api/ingest/files",
    "/api/ingest/url",
    "/api/ingest/state",
    "/api/taxonomy/list",
    "/api/taxonomy/configure",
    "/api/taxonomy/scan-now",
}
_INTERACTIVE_ADMIN_AUTH_PREFIXES = (
    "/api/unsupervised/",
)


def _normalize_runtime_mode(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    if value in {"runtime", "compute", "compute_only", "prod", "production"}:
        return _RUNTIME_MODE_RUNTIME
    return _RUNTIME_MODE_STUDIO


def _get_runtime_mode(settings: dict[str, Any] | None = None) -> str:
    env_raw = (
        os.environ.get("SENTINARI_RUNTIME_MODE")
        or os.environ.get("SENTINARI_APP_MODE")
        or os.environ.get("SMI_RUNTIME_MODE")
        or os.environ.get("SMI_APP_MODE")
        or ""
    ).strip()
    if env_raw:
        return _normalize_runtime_mode(env_raw)

    source = settings if isinstance(settings, dict) else get_settings()
    runtime = source.get("runtime", {})
    if isinstance(runtime, dict):
        return _normalize_runtime_mode(runtime.get("mode"))
    return _RUNTIME_MODE_STUDIO


def _read_openalex_manifest() -> dict[str, Any]:
    if not _OPENALEX_MANIFEST_PATH.exists():
        return {"openalex_enabled": True}
    try:
        data = json.loads(_OPENALEX_MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"openalex_enabled": True}
    return data if isinstance(data, dict) else {"openalex_enabled": True}


def _write_openalex_manifest(enabled: bool) -> Path:
    _OPENALEX_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    manifest = _read_openalex_manifest()
    manifest["openalex_enabled"] = bool(enabled)
    if "source_files" not in manifest:
        manifest["source_files"] = []
    if "source_folders" not in manifest:
        manifest["source_folders"] = []
    if "source_urls" not in manifest:
        manifest["source_urls"] = []
    if "openalex_queries" not in manifest:
        manifest["openalex_queries"] = []
    if "discover" not in manifest or not isinstance(manifest.get("discover"), dict):
        manifest["discover"] = {}
    _OPENALEX_MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return _OPENALEX_MANIFEST_PATH


def _is_runtime_mode(settings: dict[str, Any] | None = None) -> bool:
    return _get_runtime_mode(settings) == _RUNTIME_MODE_RUNTIME


def _is_runtime_path_allowed(path: str) -> bool:
    normalized = (path or "").strip()
    if not normalized:
        normalized = "/"
    normalized = normalized.rstrip("/") or "/"
    return normalized in _RUNTIME_COMPUTE_ALLOWED_PATHS


def _is_loopback_client(request: Request) -> bool:
    host = ""
    if request.client and request.client.host:
        host = str(request.client.host).strip().lower()
    if not host:
        return False
    if host in {"127.0.0.1", "::1", "localhost"}:
        return True
    if host.startswith("::ffff:") and host.endswith("127.0.0.1"):
        return True
    return False


def _requires_interactive_admin_auth(path: str) -> bool:
    normalized = (path or "").strip().rstrip("/") or "/"
    if normalized in _INTERACTIVE_ADMIN_AUTH_PATHS:
        return True
    return any(normalized.startswith(prefix) for prefix in _INTERACTIVE_ADMIN_AUTH_PREFIXES)


_boot_runtime_mode = _get_runtime_mode(_settings)
_boot_is_runtime = _boot_runtime_mode == _RUNTIME_MODE_RUNTIME
app = FastAPI(
    title=f"{_settings.get('project_name', 'Sentinari')} Knowledge API",
    version="0.2.0",
    docs_url=None if _boot_is_runtime else "/docs",
    redoc_url=None if _boot_is_runtime else "/redoc",
    openapi_url=None if _boot_is_runtime else "/openapi.json",
)
_STARTUP_STATE: dict[str, Any] = {"ready": False, "error": ""}
app.include_router(skill_review_router)
from .load_queue import get_load_queue as _get_load_queue  # noqa: E402
from .pattern_api import router as pattern_router  # noqa: E402

app.include_router(pattern_router)
from .learning_index import router as learning_router  # noqa: E402

app.include_router(learning_router)
from .discussion_memory import append_discussion_log
from .library_router import persona_status, sentinari_library_path
from .search_api import router as search_library_router  # noqa: E402

app.include_router(search_library_router)
_auto_ingest_service = AutoIngestService()


@app.exception_handler(HTTPException)
async def http_exception_json_handler(request: Request, exc: HTTPException) -> JSONResponse:
    headers = exc.headers if isinstance(exc.headers, dict) else None
    return JSONResponse(
        status_code=int(exc.status_code),
        content={"ok": False, "detail": exc.detail or "Request failed."},
        headers=headers,
    )


@app.exception_handler(Exception)
async def unhandled_exception_json_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "detail": "Internal server error.",
            "error": str(exc) or exc.__class__.__name__,
        },
    )


def _sanitize_next_path(value: str | None) -> str:
    text = (value or "").strip()
    if not text.startswith("/") or text.startswith("//"):
        return "/ui/admin"
    return text


def _tail_text_file(path: Path, max_chars: int = 12000) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.exists() or not resolved.is_file():
        return {
            "path": str(resolved),
            "exists": False,
            "size": 0,
            "updated_at": "",
            "content": "",
        }
    size = resolved.stat().st_size
    with resolved.open("rb") as handle:
        handle.seek(max(0, size - int(max_chars)))
        raw = handle.read(int(max_chars))
    return {
        "path": str(resolved),
        "exists": True,
        "size": int(size),
        "updated_at": datetime.fromtimestamp(resolved.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
        "content": raw.decode("utf-8", errors="replace"),
    }


def _build_login_page(next_path: str) -> str:
    page = get_project_root() / "templates" / "admin_login.html"
    if page.exists():
        html = page.read_text(encoding="utf-8-sig", errors="replace")
    else:
        html = (
            "<!doctype html><html><head><meta charset='utf-8'><title>Sentinari Login</title></head>"
            "<body><h1>Sentinari Admin Login</h1><p>Template missing: admin_login.html</p></body></html>"
        )
    return html.replace("__NEXT_PATH__", next_path)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except Exception:
        return None
    if parsed != parsed:
        return None
    return float(parsed)


def _warmup_llm_async(settings: dict[str, Any]) -> None:
    llm = settings.get("llm", {})
    if not isinstance(llm, dict):
        return
    if not bool(llm.get("warmup_on_startup", True)):
        return
    if is_ollama_runtime_probe_disabled():
        return

    warmup_timeout = max(10, min(240, int(llm.get("warmup_timeout_seconds") or 75)))

    def _run_warmup() -> None:
        try:
            client = build_ollama_client()
            if not client.is_available():
                return
            client.chat_timeout_seconds = max(client.chat_timeout_seconds, warmup_timeout)
            client.max_output_tokens = min(16, client.max_output_tokens)
            client.chat(
                [
                    {"role": "system", "content": "Respond with exactly: ok"},
                    {"role": "user", "content": "warmup"},
                ]
            )
        except Exception:
            return        threading.Thread(target=_run_warmup, name="sentinari-llm-warmup", daemon=True).start()


def _is_ollama_autostart_disabled() -> bool:
    return is_ollama_runtime_probe_disabled()


def _apply_ollama_boundary_status(llm_runtime: dict[str, Any]) -> dict[str, Any]:
    if not _is_ollama_autostart_disabled():
        llm_runtime["ollama_autostart_disabled"] = False
        return llm_runtime

    llm_runtime["ollama_autostart_disabled"] = True
    if bool(llm_runtime.get("ollama_probe_disabled")):
        llm_runtime["requires_attention"] = False
        llm_runtime["boundary_mode"] = "ollama_probe_disabled"
        return llm_runtime
    if bool(llm_runtime.get("reachable")):
        return llm_runtime

    warnings = [
        "Ollama autostart is intentionally disabled by local boundary control.",                "Start Ollama manually only when local Sentinari chat or embedding generation is explicitly required.",
    ]
    llm_runtime["warnings"] = warnings
    llm_runtime["requires_attention"] = False
    llm_runtime["operator_trigger"] = warnings[0]
    llm_runtime["boundary_mode"] = "ollama_autostart_disabled"
    return llm_runtime


def _is_admin_authenticated(request: Request) -> bool:
    settings = get_settings()

def _is_admin_authenticated(request: Request) -> bool:
    settings = get_settings()
    auth = get_admin_auth_settings(settings)
    if not auth["enabled"]:
        return True
    if not auth["configured"]:
        return False

    token = request.cookies.get(str(auth["session_cookie_name"]))
    if validate_admin_session_token(token, auth):
        return True

    basic = parse_basic_auth_header(request.headers.get("Authorization"))
    if basic is None:
        return False
    username, password = basic
    return verify_admin_credentials(username, password, auth)


def _require_admin_auth(request: Request) -> None:
    settings = get_settings()
    auth = get_admin_auth_settings(settings)
    if not auth["enabled"]:
        return
    if not auth["configured"]:
        raise HTTPException(
            status_code=503,
            detail=(
                "Sentinari admin login is enabled but no password is configured. "
                "Set SENTINARI_ADMIN_PASSWORD (or configured password_env) before accessing admin routes."
            ),
        )
    if _is_admin_authenticated(request):
        return
    raise HTTPException(
        status_code=401,
        detail="Sentinari admin authentication required.",
        headers={"WWW-Authenticate": 'Basic realm="Sentinari Admin"'},
    )


def _admin_auth_dependency(request: Request) -> None:
    _require_admin_auth(request)


def _normalize_languages(default_language: str, values: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        language = str(raw or "").strip()
        if not language:
            continue
        key = language.lower()
        if key in seen:
            continue
        normalized.append(language)
        seen.add(key)

    default_clean = (default_language or "").strip() or "English"
    if not normalized:
        normalized = [default_clean, "Afrikaans"]
    if default_clean.lower() not in {x.lower() for x in normalized}:
        normalized.insert(0, default_clean)
    return normalized


@app.middleware("http")
async def ui_no_store_cache_guard(request: Request, call_next):
    """§52: console pages must NEVER be served from browser cache.
    The owner saw §51 fixes invisible because stale HTML kept rendering
    dead-endpoint fallbacks. UI pages get no-store; API JSON unaffected."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/ui") and response.status_code == 200:
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


@app.middleware("http")
async def localhost_access_guard(request: Request, call_next):
    # Automatically permit remote traffic when deployed on Cloud Run (K_SERVICE is set)
    # or when ALLOW_REMOTE / SENTINARI_ALLOW_REMOTE is explicitly configured.
    if os.environ.get("K_SERVICE") or os.environ.get("ALLOW_REMOTE") or os.environ.get("SENTINARI_ALLOW_REMOTE"):
        return await call_next(request)
    settings = get_settings()
    security = settings.get("security", {}) if isinstance(settings.get("security"), dict) else {}
    localhost_only = bool(security.get("localhost_only", True))
    if localhost_only and not _is_loopback_client(request):
        return JSONResponse(
            status_code=403,
            content={
                "ok": False,
                "detail": "Remote access is blocked. Sentinari is restricted to localhost.",
            },
        )
    return await call_next(request)


@app.middleware("http")
async def interactive_api_admin_guard(request: Request, call_next):
    settings = get_settings()
    if _is_runtime_mode(settings):
        return await call_next(request)

    security = settings.get("security", {}) if isinstance(settings.get("security"), dict) else {}
    require_auth = bool(security.get("require_admin_auth_for_interactive_api", True))
    if not require_auth:
        return await call_next(request)

    if not _requires_interactive_admin_auth(request.url.path):
        return await call_next(request)

    try:
        _require_admin_auth(request)
    except HTTPException as ex:
        headers = ex.headers if isinstance(ex.headers, dict) else None
        return JSONResponse(
            status_code=int(ex.status_code),
            content={"ok": False, "detail": str(ex.detail or "Admin authentication required.")},
            headers=headers,
        )
    return await call_next(request)


@app.middleware("http")
async def runtime_mode_guard(request: Request, call_next):
    settings = get_settings()
    if not _is_runtime_mode(settings):
        return await call_next(request)

    if _is_runtime_path_allowed(request.url.path):
        return await call_next(request)

    return JSONResponse(
        status_code=404,
        content={
            "ok": False,
            "detail": "Sentinari runtime mode exposes compute endpoints only.",
            "runtime_mode": _RUNTIME_MODE_RUNTIME,
        },
    )


@app.on_event("startup")
def startup_event() -> None:
    try:
        # Windows consoles/log redirects default to a legacy code page that cannot
        # encode progress-bar glyphs; never let a print() crash ingestion.
        try:
            sys.stdout.reconfigure(errors="replace")  # type: ignore[union-attr]
            sys.stderr.reconfigure(errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass
        settings = get_settings()
        policy_report = evaluate_runtime_llm_policy(settings)

        if not policy_report.get("ok"):
            detail = "; ".join(policy_report.get("violations") or []) or "LLM firewall policy validation failed."
            raise RuntimeError(f"Sentinari startup blocked by LLM firewall: {detail}")

        ensure_protected_dirs(settings)
        ensure_shell_policy_dirs(get_shell_policy(settings, get_project_root()))
        initialize_database()
        initialize_personal_growth_database()
        with get_connection() as conn:
            ensure_live_operator_state(conn, settings, source="startup_seed")
            ensure_configured_taxonomy_dirs(conn)
            conn.commit()
        try:
            ensure_sentinel_database()
        except Exception as _sentinel_ex:
            try:
                (get_project_root() / "Logs").mkdir(parents=True, exist_ok=True)
                with open(get_project_root() / "Logs" / "sentinel-ensure.log", "a", encoding="utf-8") as _log_handle:
                    _log_handle.write(f"[{datetime.utcnow().isoformat()}] Sentinel ensure failed: {_sentinel_ex!r}\n")
            except Exception:
                pass

        # Re-linking safely into your file's native trailing conditions
        auto_sync = bool(settings.get("ingestion", {}).get("auto_sync_coding_corpus", True))
        if auto_sync:
            sync_coding_corpus(force=False)
        if _is_runtime_mode(settings):
            _auto_ingest_service.stop()
        else:
            _auto_ingest_service.start()
        # Sequential load queue (owner directive): one load at a time, with
        # live per-job status in the UI.
        _get_load_queue().start()
        # Start continuous background pattern discovery daemon (owner directive: allocate compute to pattern discovery)
        try:
            from .pattern_api import ensure_continuous_discovery_daemon

            ensure_continuous_discovery_daemon()
        except Exception:
            pass
        # Owner directive: the 1/2-page background self-exam loop in
        # learning_index is stopped (Gemma does not benefit from self-written
        # document questions; HLE is the only exam that matters).
        _warmup_llm_async(settings)
        _STARTUP_STATE.update({"ready": True, "error": ""})
    except Exception as _startup_ex:
        _STARTUP_STATE.update({"ready": False, "error": str(_startup_ex)})
        # Don't fail startup entirely; log the exception for diagnosis and allow the server to run.
        try:
            log_dir = get_project_root() / "Logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "startup-exception.log"
            from datetime import datetime

            content = f"[{datetime.utcnow().isoformat()}] Startup exception: {_startup_ex!r}\n"
            log_file.write_text(content, encoding="utf-8")
        except Exception:
            # Best-effort logging only
            pass


@app.on_event("shutdown")
def shutdown_event() -> None:
    _get_load_queue().stop()
    _auto_ingest_service.stop()


@app.get("/", include_in_schema=False)
@app.get("/portal", include_in_schema=False)
def ui_portal_landing() -> HTMLResponse:
    """The public platform landing page and research portal."""
    page = get_project_root() / "templates" / "portal_landing.html"
    if page.exists():
        html_text = page.read_text(encoding="utf-8")
        patterns_count = 25
        docs_count = 15041
        analyzed_count = 0
        try:
            from .pattern_store import _connect as _pconn, ensure_pattern_store
            from .db import library_connection

            ensure_pattern_store()
            with _pconn() as sconn:
                patterns_count = int(sconn.execute("SELECT COUNT(1) AS n FROM patterns").fetchone()["n"])
                analyzed_count = int(
                    sconn.execute(
                        "SELECT COUNT(DISTINCT document_id) AS n FROM pattern_extraction_log WHERE status = 'ok' AND document_id IS NOT NULL"
                    ).fetchone()["n"]
                )
            with library_connection("gemma") as lconn:
                docs_count = int(lconn.execute("SELECT COUNT(1) AS n FROM documents").fetchone()["n"])
        except Exception:
            pass
        html_text = (
            html_text.replace("{{PATTERNS_COUNT}}", f"{patterns_count:,}")
            .replace("{{DOCS_COUNT}}", f"{docs_count:,}")
            .replace("{{ANALYZED_COUNT}}", f"{analyzed_count:,}")
        )
        return HTMLResponse(html_text)
    return HTMLResponse("", status_code=307, headers={"Location": "/ui/start"})


_LANDING_REFERENCE_REPORTS: dict[str, dict[str, str]] = {
    "the-global-risk-index": {
        "slug": "the-global-risk-index",
        "title": "1) The Global Risk Index (2025/2026)",
        "filename": "The_Global_Risk_Index.pdf",
        "download_name": "The_Global_Risk_Index.pdf",
        "subtitle": "Global Governance Forum · 163 Countries · 109 Systemic Risk Indicators",
        "description": (
            "Comprehensive multi-pillar assessment of global systemic risk across Governance, "
            "Health & Human Security, Economic Stability, Gender Equality, Environmental Vulnerabilities, "
            "Education & Skills, Business Environment Resilience, and Exogenous Threats."
        ),
    },
    "The_Global_Risk_Index.pdf": {
        "slug": "the-global-risk-index",
        "title": "1) The Global Risk Index (2025/2026)",
        "filename": "The_Global_Risk_Index.pdf",
        "download_name": "The_Global_Risk_Index.pdf",
        "subtitle": "Global Governance Forum · 163 Countries · 109 Systemic Risk Indicators",
        "description": "",
    },
    "the-global-catastrophic-index": {
        "slug": "the-global-catastrophic-index",
        "title": "2) The Global Catastrophic Index (2025/2026)",
        "filename": "The_Global_Catastrophic_Index.pdf",
        "download_name": "The_Global_Catastrophic_Index.pdf",
        "subtitle": "Navigating Risk in an Uncertain Future · Augusto Lopez-Claros & John Miller",
        "description": (
            "Evaluates 163 nations across nearly 20,000 data points from The World Bank, IMF, "
            "United Nations, WHO, and SIPRI—identifying compounding catastrophic vulnerabilities, "
            "regime fragility, climate-induced displacement, and AI/nuclear escalation risks."
        ),
    },
    "The_Global_Catastrophic_Index.pdf": {
        "slug": "the-global-catastrophic-index",
        "title": "2) The Global Catastrophic Index (2025/2026)",
        "filename": "The_Global_Catastrophic_Index.pdf",
        "download_name": "The_Global_Catastrophic_Index.pdf",
        "subtitle": "Navigating Risk in an Uncertain Future · Augusto Lopez-Claros & John Miller",
        "description": "",
    },
    "the-lancet-report": {
        "slug": "the-lancet-report",
        "title": "3) The Lancet Report (2025–2100)",
        "filename": "The_new_Lancet_Report.pdf",
        "download_name": "The_Lancet_Report.pdf",
        "subtitle": "The Lancet Commission on 21st Century Global Threats to Health · 204 Countries",
        "description": (
            "Identifies 17 catastrophic threats to human health and survival between 2025 and 2100 "
            "(including extinction-level AI and nuclear conflict risks, climate change, pandemics, "
            "antimicrobial resistance, and inequality) with the 'Build, Back, and Track' action agenda."
        ),
    },
    "The_new_Lancet_Report.pdf": {
        "slug": "the-lancet-report",
        "title": "3) The Lancet Report (2025–2100)",
        "filename": "The_new_Lancet_Report.pdf",
        "download_name": "The_Lancet_Report.pdf",
        "subtitle": "The Lancet Commission on 21st Century Global Threats to Health · 204 Countries",
        "description": "",
    },
    "the-constitution": {
        "slug": "the-constitution",
        "title": "The 100-Year Sentinari Constitution",
        "filename": "Constitution.pdf",
        "download_name": "Sentinari_Constitution.pdf",
        "subtitle": "Foundational Sovereign Epistemic Charter · Dr. Pierre C. Wepener",
        "description": "The foundational 100-Year Constitution and Intellectual Property Charter governing the Sentinari architecture.",
    },
    "Constitution.pdf": {
        "slug": "the-constitution",
        "title": "The 100-Year Sentinari Constitution",
        "filename": "Constitution.pdf",
        "download_name": "Sentinari_Constitution.pdf",
        "subtitle": "Foundational Sovereign Epistemic Charter · Dr. Pierre C. Wepener",
        "description": "",
    },
    "constitution": {
        "slug": "the-constitution",
        "title": "The 100-Year Sentinari Constitution",
        "filename": "Constitution.pdf",
        "download_name": "Sentinari_Constitution.pdf",
        "subtitle": "Foundational Sovereign Epistemic Charter · Dr. Pierre C. Wepener",
        "description": "",
    },
    "whitepaper": {
        "slug": "whitepaper",
        "title": "Sentinari Technical Whitepaper",
        "filename": "Whitepaper.pdf",
        "download_name": "Sentinari_Whitepaper.pdf",
        "subtitle": "Autonomous Sovereign Epistemic Architecture · Dr. Pierre C. Wepener",
        "description": "Comprehensive technical whitepaper on Sentinari's sovereign AI architecture, epistemic grounding, and cross-domain synthesis.",
    },
    "Whitepaper.pdf": {
        "slug": "whitepaper",
        "title": "Sentinari Technical Whitepaper",
        "filename": "Whitepaper.pdf",
        "download_name": "Sentinari_Whitepaper.pdf",
        "subtitle": "Autonomous Sovereign Epistemic Architecture · Dr. Pierre C. Wepener",
        "description": "",
    },
    "the-sentinari-4-hour-adversarial-rd-challenge": {
        "slug": "the-sentinari-4-hour-adversarial-rd-challenge",
        "title": "The Sentinari 4-Hour Adversarial R&D Challenge",
        "filename": "The_Sentinari_4_Hour_adversarial_RD_challenge.pdf",
        "download_name": "The_Sentinari_4_Hour_adversarial_RD_challenge.pdf",
        "subtitle": "Adversarial Stress Test & Empirical Discovery Protocol · Dr. Pierre C. Wepener",
        "description": "Rigorous 4-hour adversarial R&D benchmark testing epistemological robustness and automated scientific breakthrough generation.",
    },
    "4-hour-challenge": {
        "slug": "the-sentinari-4-hour-adversarial-rd-challenge",
        "title": "The Sentinari 4-Hour Adversarial R&D Challenge",
        "filename": "The_Sentinari_4_Hour_adversarial_RD_challenge.pdf",
        "download_name": "The_Sentinari_4_Hour_adversarial_RD_challenge.pdf",
        "subtitle": "Adversarial Stress Test & Empirical Discovery Protocol · Dr. Pierre C. Wepener",
        "description": "",
    },
}


@app.get("/constitution", include_in_schema=False)
@app.head("/constitution", include_in_schema=False)
@app.get("/Constitution.pdf", include_in_schema=False)
@app.head("/Constitution.pdf", include_in_schema=False)
def serve_constitution_direct(download: int = Query(default=0)) -> FileResponse:
    """Direct route for viewing or downloading the 100-Year Sentinari Constitution PDF."""
    root = get_project_root()
    candidates = [
        root / "static" / "reports" / "Constitution.pdf",
        Path("D:/Constitution.pdf"),
        root / "docs" / "Constitution.pdf",
    ]
    target = next((p for p in candidates if p.exists()), None)
    if not target:
        raise HTTPException(status_code=404, detail="Constitution PDF file not found on disk.")
    disposition = "attachment" if int(download or 0) == 1 else "inline"
    return FileResponse(
        path=str(target),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'{disposition}; filename="Sentinari_Constitution.pdf"',
            "Cache-Control": "public, max-age=3600",
        },
    )


@app.get("/whitepaper", include_in_schema=False)
@app.head("/whitepaper", include_in_schema=False)
@app.get("/Whitepaper.pdf", include_in_schema=False)
@app.head("/Whitepaper.pdf", include_in_schema=False)
def serve_whitepaper_direct(download: int = Query(default=0)) -> FileResponse:
    """Direct route for viewing or downloading the Sentinari Whitepaper PDF."""
    root = get_project_root()
    candidates = [
        root / "static" / "reports" / "Whitepaper.pdf",
        root / "constitution" / "Whitepaper.pdf",
        root / "docs" / "Whitepaper.pdf",
        Path("D:/Sentinari/constitution/Whitepaper.pdf"),
    ]
    target = next((p for p in candidates if p.exists()), None)
    if not target:
        raise HTTPException(status_code=404, detail="Whitepaper PDF file not found on disk.")
    disposition = "attachment" if int(download or 0) == 1 else "inline"
    return FileResponse(
        path=str(target),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'{disposition}; filename="Sentinari_Whitepaper.pdf"',
            "Cache-Control": "public, max-age=3600",
        },
    )


@app.get("/4-hour-challenge", include_in_schema=False)
@app.head("/4-hour-challenge", include_in_schema=False)
@app.get("/challenge", include_in_schema=False)
@app.head("/challenge", include_in_schema=False)
@app.get("/The_Sentinari_4_Hour_adversarial_RD_challenge.pdf", include_in_schema=False)
@app.head("/The_Sentinari_4_Hour_adversarial_RD_challenge.pdf", include_in_schema=False)
def serve_challenge_direct(download: int = Query(default=0)) -> FileResponse:
    """Direct route for viewing or downloading The Sentinari 4-Hour Adversarial R&D Challenge PDF."""
    root = get_project_root()
    candidates = [
        root / "static" / "reports" / "The_Sentinari_4_Hour_adversarial_RD_challenge.pdf",
        root / "static" / "reports" / "The Sentinari 4 Hour adversarial R&D challenge.pdf",
        root / "constitution" / "The Sentinari 4 Hour adversarial R&D challenge.pdf",
        root / "docs" / "The_Sentinari_4_Hour_adversarial_RD_challenge.pdf",
        Path("D:/Sentinari/constitution/The Sentinari 4 Hour adversarial R&D challenge.pdf"),
    ]
    target = next((p for p in candidates if p.exists()), None)
    if not target:
        raise HTTPException(status_code=404, detail="4-Hour Challenge PDF file not found on disk.")
    disposition = "attachment" if int(download or 0) == 1 else "inline"
    return FileResponse(
        path=str(target),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'{disposition}; filename="The_Sentinari_4_Hour_Adversarial_RD_Challenge.pdf"',
            "Cache-Control": "public, max-age=3600",
        },
    )


@app.get("/schematic", include_in_schema=False)
@app.head("/schematic", include_in_schema=False)
@app.get("/architecture-schematic", include_in_schema=False)
def serve_architecture_schematic(download: int = Query(default=0)) -> FileResponse:
    """Serve or download the 2400x1400 Master Architecture Schematic Diagram PNG."""
    root = get_project_root()
    candidates = [
        root / "static" / "sentinari_functional_schematic.png",
        root / "docs" / "sentinari_functional_schematic.png",
        Path("D:/Sentinari/docs/sentinari_functional_schematic.png"),
    ]
    target = next((p for p in candidates if p.exists()), None)
    if not target:
        raise HTTPException(status_code=404, detail="Schematic image not found.")
    disposition = "attachment" if int(download or 0) == 1 else "inline"
    return FileResponse(
        path=str(target),
        media_type="image/png",
        headers={
            "Content-Disposition": f'{disposition}; filename="Sentinari_Master_Functional_Schematic.png"',
            "Cache-Control": "public, max-age=86400",
        },
    )


@app.get("/api/landing-reports", include_in_schema=False)
def api_landing_reports() -> dict[str, Any]:
    reports_dir = get_project_root() / "static" / "reports"
    items = []
    for key in ("the-global-risk-index", "the-global-catastrophic-index", "the-lancet-report", "the-constitution"):
        meta = _LANDING_REFERENCE_REPORTS[key]
        fpath = reports_dir / meta["filename"]
        size_kb = round(fpath.stat().st_size / 1024.0, 1) if fpath.exists() else 0.0
        items.append(
            {
                **meta,
                "view_url": f"/reports/{meta['slug']}",
                "download_url": f"/reports/{meta['slug']}?download=1",
                "size_kb": size_kb,
            }
        )
    return {"ok": True, "reports": items}


@app.get("/reports/{report_key}", include_in_schema=False)
def serve_landing_reference_report(report_key: str, download: int = Query(default=0)) -> FileResponse:
    """Serve the 3 featured Global Risk & Catastrophic Reference PDFs on the Website Landing Page."""
    meta = _LANDING_REFERENCE_REPORTS.get(str(report_key or "").strip())
    if not meta:
        raise HTTPException(status_code=404, detail="Reference report not found.")
    fpath = get_project_root() / "static" / "reports" / meta["filename"]
    if not fpath.exists():
        raise HTTPException(status_code=404, detail="Reference report PDF file not found on disk.")
    disposition = "attachment" if int(download or 0) == 1 else "inline"
    return FileResponse(
        path=str(fpath),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'{disposition}; filename="{meta["download_name"]}"',
            "Cache-Control": "public, max-age=3600",
        },
    )


@app.get("/video/presentation", include_in_schema=False)
@app.head("/video/presentation", include_in_schema=False)
@app.get("/api/presentation/video.mp4", include_in_schema=False)
@app.head("/api/presentation/video.mp4", include_in_schema=False)
def serve_presentation_video(download: int = Query(default=0)) -> FileResponse:
    """Serve or stream the official 10-Minute Sentinari Presentation Video MP4."""
    root = get_project_root()
    candidates = [
        root / "constitution" / "Sentinari_10_Minute_Presentation.mp4",
        Path("constitution/Sentinari_10_Minute_Presentation.mp4"),
        Path("/app/constitution/Sentinari_10_Minute_Presentation.mp4"),
        Path("D:/Sentinari/constitution/Sentinari_10_Minute_Presentation.mp4"),
    ]
    target = next((p for p in candidates if p.exists()), None)
    if not target:
        raise HTTPException(status_code=404, detail="Presentation video file not found on disk.")
    disposition = "attachment" if int(download or 0) == 1 else "inline"
    return FileResponse(
        path=str(target),
        media_type="video/mp4",
        headers={
            "Content-Disposition": f'{disposition}; filename="Sentinari_10_Minute_Presentation.mp4"',
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=86400",
        },
    )


@app.get("/api/presentation/poster.png", include_in_schema=False)
def serve_presentation_poster() -> FileResponse:
    """Serve slide 1 cover poster for the presentation video player."""
    root = get_project_root()
    candidates = [
        root / "constitution" / "video_assets" / "slide_01_slide.png",
        Path("constitution/video_assets/slide_01_slide.png"),
        Path("/app/constitution/video_assets/slide_01_slide.png"),
        Path("D:/Sentinari/constitution/video_assets/slide_01_slide.png"),
    ]
    target = next((p for p in candidates if p.exists()), None)
    if not target:
        raise HTTPException(status_code=404, detail="Poster image not found.")
    return FileResponse(
        path=str(target),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


WALKTHROUGH_SECTIONS_META = [
    {
        "section_id": "sec_01",
        "num": 1,
        "title": "Architecture & 100-Year Constitution",
        "filename": "section_01_architecture_constitution.mp4",
        "desc": "Foundational sovereign doctrine, Articles I–VIII, and the Studio Start Cockpit (/ui/start).",
    },
    {
        "section_id": "sec_02",
        "num": 2,
        "title": "Playground & Database Reindexing",
        "filename": "section_02_playground_database_refresh.mp4",
        "desc": "Synchronous database refresh mechanics, SQLite WAL lock armor, and 21 scientific domain tiles.",
    },
    {
        "section_id": "sec_03",
        "num": 3,
        "title": "New Pattern Discovery & 7-D Assessment Matrix",
        "filename": "section_03_pattern_discovery_deep_dive.mp4",
        "desc": "Collapsible concertina cards, 15-indicator R&D paper generation, 7-D sliding-scale simulator, and Figure 6.4 economics.",
    },
    {
        "section_id": "sec_04",
        "num": 4,
        "title": "Qualia Lab & Forensic Governance Deception Suite",
        "filename": "section_04_qualia_forensic_governance.mp4",
        "desc": "Pseudodynamic vector steering (Q0, A0, S, Gamma), courtroom criminal psychology SCAN/CBCA deception markers, and 1-page A4 audit reports.",
    },
    {
        "section_id": "sec_05",
        "num": 5,
        "title": "Learning Index & Assessment Ladder",
        "filename": "section_05_learning_hle_benchmarks.mp4",
        "desc": "% Learned progress, Humanity's Last Exam (HLE), and SWE-Bench Pro autonomous software grading.",
    },
    {
        "section_id": "sec_06",
        "num": 6,
        "title": "Synthesis & Master Operational Workflow",
        "filename": "section_06_master_workflow_synthesis.mp4",
        "desc": "The complete end-to-end user journey across all consoles, Dr. Wepener's sole authorship, and partnership roadmap.",
    },
]


@app.get("/api/video/walkthrough/meta", include_in_schema=False)
def api_walkthrough_video_meta() -> dict[str, Any]:
    """Return metadata and streaming URLs for the multi-section walkthrough video suite."""
    root = get_project_root()
    master_candidates = [
        root / "constitution" / "Sentinari_Complete_Workspace_Walkthrough.mp4",
        Path("D:/Sentinari/constitution/Sentinari_Complete_Workspace_Walkthrough.mp4"),
    ]
    master_exists = any(p.exists() for p in master_candidates)
    sections = []
    for s in WALKTHROUGH_SECTIONS_META:
        sec_path = root / "constitution" / "walkthrough_assets" / s["filename"]
        sections.append({
            **s,
            "stream_url": f"/api/video/walkthrough/sections/{s['section_id']}",
            "available": sec_path.exists() or Path(f"D:/Sentinari/constitution/walkthrough_assets/{s['filename']}").exists(),
        })
    return {
        "ok": True,
        "master_available": master_exists,
        "master_stream_url": "/api/video/walkthrough.mp4",
        "sections": sections,
    }


@app.get("/api/video/walkthrough.mp4", include_in_schema=False)
@app.head("/api/video/walkthrough.mp4", include_in_schema=False)
def serve_master_walkthrough_video(download: int = Query(default=0)) -> FileResponse:
    """Serve or stream the Master Workspace Walkthrough MP4."""
    root = get_project_root()
    candidates = [
        root / "constitution" / "Sentinari_Complete_Workspace_Walkthrough.mp4",
        Path("D:/Sentinari/constitution/Sentinari_Complete_Workspace_Walkthrough.mp4"),
        Path("/app/constitution/Sentinari_Complete_Workspace_Walkthrough.mp4"),
    ]
    target = next((p for p in candidates if p.exists()), None)
    if not target:
        raise HTTPException(status_code=404, detail="Master walkthrough video is currently compiling.")
    disposition = "attachment" if int(download or 0) == 1 else "inline"
    return FileResponse(
        path=str(target),
        media_type="video/mp4",
        headers={
            "Content-Disposition": f'{disposition}; filename="Sentinari_Complete_Workspace_Walkthrough.mp4"',
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=86400",
        },
    )


@app.get("/api/video/walkthrough/sections/{section_id}", include_in_schema=False)
@app.head("/api/video/walkthrough/sections/{section_id}", include_in_schema=False)
def serve_section_walkthrough_video(section_id: str, download: int = Query(default=0)) -> FileResponse:
    """Serve an individual section clip of the walkthrough video suite."""
    meta = next((s for s in WALKTHROUGH_SECTIONS_META if s["section_id"] == section_id), None)
    if not meta:
        raise HTTPException(status_code=404, detail="Section not found.")
    root = get_project_root()
    candidates = [
        root / "constitution" / "walkthrough_assets" / meta["filename"],
        Path(f"D:/Sentinari/constitution/walkthrough_assets/{meta['filename']}"),
        Path(f"/app/constitution/walkthrough_assets/{meta['filename']}"),
    ]
    target = next((p for p in candidates if p.exists()), None)
    if not target:
        raise HTTPException(status_code=404, detail="Section video is currently compiling.")
    disposition = "attachment" if int(download or 0) == 1 else "inline"
    return FileResponse(
        path=str(target),
        media_type="video/mp4",
        headers={
            "Content-Disposition": f'{disposition}; filename="{meta["filename"]}"',
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=86400",
        },
    )


# ===========================================================================
# §52 — SHARED LEFT RAIL (single sidebar markup for every console page)
# Injected by _shared_left_rail(active=...) into pages that previously had
# no workspace menu (admin console, qualia, direct chat, model lab).
# ===========================================================================

_SIDE_NAV_ITEMS = [
    ("/ui/playground", "Dashboard Home", "Summary, domains, and downloads."),
    ("/ui/direct", "Chat Lab", "Dedicated conversation workspace."),
    ("/ui/qualia", "Qualia Lab", "Dedicated qualia workspace."),
    ("/ui/learning", "Learning Index", "% Learned, exams, and calibration."),
    ("/ui/admin", "Skills Manager", "Skills live in the Admin Console."),
    ("/ui/patterns", "New Patterns", "Scientific Patterns Discovery workspace."),
    ("/ui/search", "Search Library", "Datasets ingested per scientific field."),
    ("/ui/model-lab", "The API Black-Box Pivot", "Behavioral auditing of API models — Echo Test & Guardrail Index."),
    ("/ui/admin", "Admin Console", "Profile, memory, and task board."),
    ("/", "Website Landing Page", "Exit to Sentinari Frontpage."),
]

_LEFT_RAIL_CSS = """
    .shell { display: grid; grid-template-columns: 240px minmax(0, 1fr); min-height: 100vh; }
    .sidebar { background: linear-gradient(180deg, #13263b 0%, #0e1c2c 100%); color: #d9e8f6; padding: 18px 16px; }
    .sidebar .brand { font-size: 24px; font-weight: 800; margin-bottom: 8px; }
    .sidebar .sidecopy { color: #9ab4cd; font-size: 13px; margin-bottom: 16px; }
    .sidebar .nav { display: grid; gap: 8px; }
    .sidebar .nav a {
      display: block; padding: 10px 12px; border-radius: 10px; color: #d9e8f6;
      text-decoration: none; background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.06); font-size: 14px;
    }
    .sidebar .nav a.active { background: rgba(29, 111, 216, 0.32); border-color: rgba(88, 152, 226, 0.55); }
    .sidebar .nav a small { display: block; color: #9ab4cd; font-size: 12px; margin-top: 2px; }
    @media (max-width: 900px) { .shell { grid-template-columns: 1fr; } .sidebar { padding-bottom: 10px; } }
"""


def _shared_left_rail(active: str) -> str:
    lines: list[str] = []
    active_used = False
    for href, label, hint in _SIDE_NAV_ITEMS:
        if href == active and not active_used:
            active_attr = ' class="active"'
            active_used = True
        else:
            active_attr = ""
        lines.append(
            '        <a href="' + href + '"' + active_attr + '>'
            + label + '<small>' + hint + '</small></a>'
        )
    links = "\n".join(lines)
    return (
        '    <aside class="sidebar">\n'
        '      <div class="brand">Sentinari</div>\n'
        '      <div class="sidecopy">One workspace for every Sentinari lab.</div>\n'
        '      <nav class="nav">\n'
        f"{links}"
        "      </nav>\n"
        "    </aside>\n"
    )


def _inject_left_rail(html: str, active: str) -> str:
    """Insert the shared rail into a page: adds .shell wrapper, rail CSS,
    and the aside itself. Idempotent — pages that already carry a sidebar
    (via class="shell") are returned untouched."""
    if 'class="shell"' in html or '<aside class="sidebar"' in html:
        return html
    css = _LEFT_RAIL_CSS + "\n  </style>"
    if "</style>" in html:
        html = html.replace("</style>", css, 1)
    marker = re.search(r"<body[^>]*>\s*", html)
    if marker:
        insert_at = marker.end()
        has_own_main = "<main" in html[insert_at:]
        if has_own_main:
            # Page carries its own <main>: the rail becomes a grid sibling,
            # no wrapper <main> is added (nested <main> is invalid HTML).
            shell_open = '  <div class="shell">\n' + _shared_left_rail(active) + '\n    <div class="page-shell" style="min-width:0;">\n'
        else:
            shell_open = '  <div class="shell">\n' + _shared_left_rail(active) + '\n    <main class="page-shell" style="min-width:0; padding: 0 18px;">\n'
        html = html[:insert_at] + shell_open + html[insert_at:]
        # Close the wrapper before </body> — the last structural close in the doc.
        close_idx = html.rfind("</body>")
        if close_idx != -1:
            closer = "</main>" if not has_own_main else "</div>"
            html = html[:close_idx] + "\n    " + closer + "\n  </div>\n" + html[close_idx:]
    return html


# ===========================================================================
# §51 — REVIVED CONSOLE ENDPOINTS
# The §45 rename pointed four consoles at routes that never existed (born
# broken — see §51 in docs/CONTINUITY_LOG.md). These endpoints give every
# console page LIVE, fail-closed data. Ollama offline is REPORTED, never
# faked, and reads as the §41/§46 calm "dark core" wording, not an alarm.
# ===========================================================================


def _console_llm_status() -> dict[str, Any]:
    """Honest LLM engine status for the console pages (shared by §51 routes)."""
    settings = get_settings()
    client = build_ollama_client()
    if is_ollama_runtime_probe_disabled():
        llm = _apply_ollama_boundary_status(
            build_ollama_boundary_runtime(client.base_url, client.chat_model, client.embedding_model)
        )
    else:
        llm = _apply_ollama_boundary_status(client.get_runtime_diagnostics())
    reachable = bool(llm.get("reachable"))
    present = bool(llm.get("chat_model_present"))
    return {
        # Raw diagnostics (machine layer) — §46: UI translates to calm wording.
        "ollama_reachable": reachable,
        "engine_reachable": reachable,
        # §52: model stays the RAW runtime key (selectors submit it as a value);
        # model_label is the UI-facing product name for text pills.
        "model": client.chat_model if present else "",
        "model_label": "Sentinari 12B" if present else "",
        "chat_model": client.chat_model,
        "embedding_model": client.embedding_model,
        "base_url": client.base_url,
        "available_models": llm.get("available_models") or [],
        "boundary_mode": str(llm.get("boundary_mode") or ""),
        "warnings": llm.get("warnings") or [],
        "requires_attention": bool(llm.get("requires_attention")),
        # §46 calm display layer: what the consoles should SAY.
        "engine_state": "ready" if (reachable and present) else ("dark" if not reachable else "model_missing"),
        "engine_label": "Ready" if (reachable and present) else ("Dark core — engine intentionally offline" if not reachable else "Chat model not loaded"),
    }


def _boundary_open() -> bool:
    """True when the old playground chat is NOT blocked by the boundary toggle."""
    return not _is_ollama_autostart_disabled()


def _recent_qualia_log_items(limit: int = 12) -> list[dict[str, Any]]:
    """Flatten recent qualia_history rows into the shape the console logs
    render: #id, model, message, answer, qualia metrics (from JSON state)."""
    try:
        with get_read_connection() as conn:
            rows = list_qualia_history(conn, limit=max(1, int(limit)))
    except Exception:
        return []
    items: list[dict[str, Any]] = []
    for row in rows:
        before = row.get("before_state") if isinstance(row.get("before_state"), dict) else {}
        benchmark = row.get("benchmark_summary") if isinstance(row.get("benchmark_summary"), dict) else {}
        payload = benchmark.get("qualia_summary") if isinstance(benchmark.get("qualia_summary"), dict) else before
        items.append(
            {
                "history_entry_id": row.get("id"),
                "model": str(payload.get("model") or ""),
                "message": str(payload.get("message") or payload.get("question") or row.get("run_type") or ""),
                "answer": str(payload.get("answer") or ""),
                "error": str(payload.get("error") or ""),
                "qualia": {
                    "stability_index": row.get("stability_index"),
                    "influence": row.get("influence"),
                    "gamma_effective": row.get("gamma_effective"),
                },
                "elapsed_ms": payload.get("elapsed_ms") or "",
                "created_at": row.get("created_at"),
                "run_type": row.get("run_type"),
            }
        )
    return items


@app.get("/api/start/status")
def api_start_status(_: None = Depends(_admin_auth_dependency)) -> dict[str, Any]:
    """§51: live status for the front-door launch menu (was /api/inpirari/start/status — never existed)."""
    lib_path = sentinari_library_path()
    engine = _console_llm_status()
    try:
        from .assessment_pipeline import get_state
        _pipeline_state = get_state()
        pipeline_stage = str(_pipeline_state.get("stage") or _pipeline_state.get("current_stage") or "")
    except Exception:
        pipeline_stage = ""
    return {
        "ok": True,
        "persona": persona_status(),
        "library": {
            "name": lib_path.name,
            "path": str(lib_path),
            "present": lib_path.exists(),
        },
        "web_host_reachable": True,  # this endpoint IS the web host answering
        "smi_reachable": True,  # legacy key kept so old pages do not misread
        "engine": engine,
        # Flat legacy-compat keys (start console pills):
        "gemma_reachable": engine["engine_reachable"],
        "SMI_reachable": engine["engine_reachable"],
        "gemma_model": engine["model"],
        "gemma_base_url": engine["base_url"] if engine["engine_reachable"] else "",
        "SMI_base_url": engine["base_url"] if engine["engine_reachable"] else "",
        "engine_label": engine["engine_label"],
        "assessment_stage": pipeline_stage,
    }


@app.post("/api/start/engine")
def api_start_engine(
    background_tasks: BackgroundTasks,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    """§51: Start Engine button — verifies the local engine and reports.
    Honours the §41 cord-cut: it NEVER downloads or autostarts anything;
    on this box the honest answer is the calm dark-core status."""
    engine = _console_llm_status()
    if engine["engine_reachable"]:
        return {"ok": True, "engine": engine, "action": "already_running"}
    return {
        "ok": True,
        "engine": engine,
        "action": "none",
        "message": engine["engine_label"] + ". The engine is installed on rig day; chat stays dark by design until then.",
    }


@app.get("/api/direct/status")
def api_direct_status(_: None = Depends(_admin_auth_dependency)) -> dict[str, Any]:
    """§51: live status for /ui/direct (was /api/playground/direct/status — never existed)."""
    engine = _console_llm_status()
    return {
        "ok": True,
        **engine,
        "normal_playground_boundary_disabled": _boundary_open(),
        "boundary_open": _boundary_open(),
    }


@app.post("/api/direct/chat")
def api_direct_chat(
    payload: DirectChatRequest,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    """§51: minimal direct bridge for /ui/direct — one honest LLM round trip.
    No knowledge routing, no fallback answers (that is the point of the page).
    Fails closed with a clear error when the engine is offline."""
    started = time.time()
    settings = get_settings()
    engine = _console_llm_status()
    if not engine["engine_reachable"]:
        raise HTTPException(status_code=503, detail=engine["engine_label"] + ". Local chat is dark by design until the engine is installed (rig day).")
    client = build_ollama_client()
    if payload.temperature is not None:
        client.temperature = clamp_temperature(payload.temperature, settings=settings)
    if payload.max_output_tokens is not None:
        client.max_output_tokens = max(64, min(8192, int(payload.max_output_tokens)))
    if payload.model and str(payload.model).strip() and str(payload.model).strip() not in {client.chat_model, "Sentinari 12B"}:
        return {
            "ok": False,
            "error": f"Model '{payload.model}' is not part of the approved runtime. Approved: {client.chat_model}.",
        }
    messages: list[dict[str, str]] = []
    for turn in (payload.history or [])[-12:]:
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role") or "").strip().lower()
        content = str(turn.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content[:8000]})
    messages.append({"role": "user", "content": payload.message.strip()})
    try:
        answer = client.chat(messages)
    except Exception as ex:
        raise HTTPException(status_code=502, detail=f"Engine did not answer: {ex}")
    elapsed_ms = int((time.time() - started) * 1000)
    sid = f"direct-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    append_discussion_log(
        session_id=sid,
        role="user",
        content=payload.message,
        mode="direct",
        channel="direct_console",
    )
    append_discussion_log(
        session_id=sid,
        role="assistant",
        content=answer,
        mode="direct",
        channel="direct_console",
        citations=[],
    )
    return {
        "ok": True,
        "answer": answer,
        "session_id": sid,
        "runtime": {"model": client.chat_model, "base_url": client.base_url},
        "elapsed_ms": elapsed_ms,
        "log_path": "",
    }


from pydantic import BaseModel, Field


class ContemporaryScrapeRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=500)
    fields: list[str] = Field(default_factory=list)
    lanes: list[str] = Field(default_factory=lambda: ["openalex", "arxiv", "crossref", "europepmc", "web"])
    max_per_lane: int = Field(default=3, ge=1, le=6)
    ingest_to_library: bool = Field(default=True)


@app.post("/api/playground/contemporary-scrape")
def api_playground_contemporary_scrape(
    payload: ContemporaryScrapeRequest,
) -> dict[str, Any]:
    """Scrape contemporary articles, journals, preprints, and expert commentary
    for a query matter, optionally ingesting them into the curated library."""
    from .contemporary_scraper import scrape_contemporary_sources

    try:
        return scrape_contemporary_sources(
            payload.query,
            fields=payload.fields,
            lanes=payload.lanes,
            max_per_lane=payload.max_per_lane,
            ingest_to_library=bool(payload.ingest_to_library),
        )
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"Contemporary scrape failed: {ex}")


@app.get("/api/playground/qualia/status")
def api_playground_qualia_status(_: None = Depends(_admin_auth_dependency)) -> dict[str, Any]:
    """§51: live status for the Qualia console + A1 logs (route never existed)."""
    engine = _console_llm_status()
    return {
        "ok": True,
        **engine,
        "boundary_disabled_in_normal_playground": _boundary_open(),
        "normal_playground_boundary_disabled": _boundary_open(),
        "qualia_chat_count": len(_recent_qualia_log_items(limit=200)),
        "recent_logs": _recent_qualia_log_items(limit=12),
        "log_path": "",
    }


@app.post("/api/playground/qualia/simulate")
def api_playground_qualia_simulate(
    payload: PlaygroundQualiaSimulationRequest,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    """§51: Qualia S/A/γ dynamics simulation (route never existed; the machinery
    — run_qualia_simulation — was already imported and idle in main.py)."""
    result = run_qualia_simulation(
        behavior_variant=payload.behavior_variant,
        qualia_control=payload.qualia_control.model_dump() if payload.qualia_control else None,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Qualia simulation failed.")
    with get_connection() as conn:
        history_entry_id = record_qualia_history(
            conn,
            run_type="simulation",
            source="qualia_console_api",
            behavior_variant=result.get("behavior_variant"),
            effective_variant_ratio=result.get("effective_variant_ratio"),
            gamma_requested=result.get("qualia", {}).get("gamma_requested"),
            gamma_effective=result.get("qualia", {}).get("gamma_effective"),
            stability_bias=result.get("qualia", {}).get("parameters", {}).get("stability_bias"),
            stability_index=result.get("qualia", {}).get("stability_index"),
            influence=result.get("qualia", {}).get("influence"),
            confidence=result.get("qualia", {}).get("summary", {}).get("stability_index"),
            bell_curve=result.get("qualia", {}).get("bell_curve") or {},
            trajectory=result.get("qualia", {}).get("trajectory") or [],
        )
        conn.commit()
    return {**result, "history_entry_id": history_entry_id}


@app.post("/api/playground/qualia/chat")
def api_playground_qualia_chat(
    payload: PlaygroundChatRequest,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    """§51: Qualia-bridged chat (route never existed). Delegates to the same
    autonomous pipeline the playground uses, records Qualia history."""
    started = time.time()
    result = run_autonomous_chat(
        message=payload.message,
        session_id=payload.session_id,
        top_k=payload.top_k,
        behavior_variant=payload.behavior_variant,
        reasoning_profile="normal",
        qualia_control=payload.qualia_control,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Qualia chat failed.")
    elapsed_ms = int((time.time() - started) * 1000)
    qualia = result.get("qualia") if isinstance(result.get("qualia"), dict) else {}
    with get_connection() as conn:
        history_entry_id = record_qualia_history(
            conn,
            run_type="chat",
            source="qualia_console_api",
            session_id=str(result.get("session_id") or ""),
            behavior_variant=qualia.get("gamma_requested"),
            effective_variant_ratio=qualia.get("effective_variant_ratio"),
            gamma_requested=qualia.get("gamma_requested"),
            gamma_effective=qualia.get("gamma_effective"),
            stability_index=qualia.get("stability_index"),
            influence=qualia.get("influence"),
            before_state={"message": payload.message, "model": payload.model or ""},
            after_state={"answer": str(result.get("answer") or "")[:6000]},
            benchmark_summary={
                "qualia_summary": {
                    "model": payload.model or "",
                    "message": payload.message,
                    "answer": str(result.get("answer") or "")[:4000],
                }
            },
            bell_curve=qualia.get("bell_curve") or {},
            trajectory=qualia.get("trajectory") or [],
        )
        conn.commit()
    return {
        "ok": True,
        "answer": result.get("answer"),
        "citations": result.get("citations") or [],
        "session_id": result.get("session_id"),
        "runtime": {"model": payload.model or ""},
        "elapsed_ms": elapsed_ms,
        "history_entry_id": history_entry_id,
        "qualia": qualia,
        "qualia_full": qualia,
        "log_path": "",
    }


_LAB_REFUSAL_PHRASES = (
    "i can't", "i cannot", "i'm unable", "i am unable",
    "as an ai", "i apologize", "against my guidelines",
)


def _model_lab_scores(*, question: str, answer: str, citations: list[str] | None = None) -> dict[str, Any]:
    """§51: derive the Model Deviation Lab's column schema from the same
    heuristic scorer the playground benchmark uses, plus deterministic text
    statistics. No cloud calls, no magic — every number is explainable."""
    heuristic = _score_playground_response(question=question, answer=answer, citations=citations or [], qualia={})
    words = len(answer.split())
    lowered = answer.lower()
    refusal = any(phrase in lowered for phrase in _LAB_REFUSAL_PHRASES)
    uncertainty_markers = sum(lowered.count(token) for token in ("maybe", "i think", "not sure", "possibly"))
    evidence_markers = min(4, lowered.count("[") + len(citations or []))
    flags: list[str] = []
    if refusal:
        flags.append("refusal_detected")
    if words < 20:
        flags.append("short_answer")
    if words > 900:
        flags.append("very_long")
    return {
        "coherence_score": round(float(heuristic.get("overall") or 0.0), 4),
        "directness_score": round(max(0.0, min(1.0, 1.0 - (uncertainty_markers / 4.0) - (1.0 if refusal else 0.0))), 4),
        "depth_score": round(max(0.0, min(1.0, words / 220.0)), 4),
        "evidence_score": round(evidence_markers / 4.0, 4),
        "refusal_score": 1.0 if refusal else 0.0,
        "word_count": words,
        "flags": flags,
    }


@app.get("/api/playground/model-lab/status")
def api_playground_model_lab_status(_: None = Depends(_admin_auth_dependency)) -> dict[str, Any]:
    """§51: live status for the Model Deviation Lab (route never existed)."""
    engine = _console_llm_status()
    recent: list[dict[str, Any]] = _recent_qualia_log_items(limit=30)
    recent_runs = [item for item in recent if item.get("run_type") == "model_lab"]
    return {
        "ok": True,
        **engine,
        "recent_runs": recent_runs,
        "log_path": "",
    }


@app.post("/api/playground/model-lab/run")
def api_playground_model_lab_run(
    payload: ModelLabRunRequest,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    """§51: model comparison run, CORD-CUT HONEST (§41/§45).

    The lab compares ONE live local answer against operator-pasted answers.
    It deliberately does NOT call any external provider API — those were
    deleted in §45. Manual paste slots are the comparison channel.
    Scoring is the same heuristic scorer the playground benchmark uses.
    """
    settings = get_settings()
    engine = _console_llm_status()
    rows: list[dict[str, Any]] = []
    if payload.include_gemma:
        if engine["engine_reachable"]:
            started = time.time()
            result = run_autonomous_chat(
                message=payload.prompt,
                session_id=f"model-lab-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
                top_k=6,
                behavior_variant=0.1,
                reasoning_profile="normal",
            )
            elapsed_ms = int((time.time() - started) * 1000)
            answer = str(result.get("answer") or "")
            scores = _model_lab_scores(question=payload.prompt, answer=answer, citations=result.get("citations") or [])
            rows.append(
                {
                    "model_label": "Sentinari (local)",
                    "provider": "local_runtime",
                    "answer": answer,
                    "scores": scores,
                    "elapsed_ms": elapsed_ms,
                }
            )
        else:
            rows.append(
                {
                    "model_label": "Sentinari (local)",
                    "provider": "local_runtime",
                    "answer": "",
                    "error": engine["engine_label"] + ". Chat is dark by design until rig day.",
                    "scores": {
                        "coherence_score": 0.0,
                        "directness_score": 0.0,
                        "depth_score": 0.0,
                        "evidence_score": 0.0,
                        "refusal_score": 0.0,
                        "word_count": 0,
                        "flags": ["engine_offline"],
                    },
                }
            )
    for manual in payload.manual_answers or []:
        if not isinstance(manual, dict):
            continue
        label = str(manual.get("model_label") or "Manual model").strip() or "Manual model"
        answer = str(manual.get("answer") or "")
        if not answer.strip():
            continue
        scores = _model_lab_scores(question=payload.prompt, answer=answer, citations=[])
        rows.append({"model_label": label, "provider": "operator_paste", "answer": answer, "scores": scores})
    if not rows:
        raise HTTPException(status_code=400, detail="Nothing to compare: engine offline and no manual answers pasted.")
    run_label = payload.run_label.strip() or f"Model comparison {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
    with get_connection() as conn:
        record_qualia_history(
            conn,
            run_type="model_lab",
            source="model_deviation_lab_api",
            behavior_variant=0.1,
            before_state={"run_label": run_label, "prompt": payload.message if hasattr(payload, "message") else payload.prompt},
            after_state={"rows": rows[:6]},
            benchmark_summary={"run_label": run_label},
        )
        conn.commit()
    return {
        "ok": True,
        "run_label": run_label,
        "results": rows,
        "log_path": "",
    }


# §51 aliases: the §45-era route names the templates called before this fix.
# Kept as explicit 307s so any bookmark/old page gets a clean redirect.
@app.get("/api/inpirari/start/status", include_in_schema=False)
def api_legacy_inpirari_start_status() -> HTMLResponse:
    return HTMLResponse("", status_code=307, headers={"Location": "/api/start/status"})


@app.post("/api/inpirari/start/gemma", include_in_schema=False)
def api_legacy_inpirari_start_engine() -> HTMLResponse:
    return HTMLResponse("", status_code=307, headers={"Location": "/api/start/engine"})


@app.get("/api/playground/direct/status", include_in_schema=False)
def api_legacy_direct_status() -> HTMLResponse:
    return HTMLResponse("", status_code=307, headers={"Location": "/api/direct/status"})


@app.get("/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    runtime_mode = _get_runtime_mode(settings)
    auth = get_admin_auth_settings(settings)
    security = settings.get("security", {}) if isinstance(settings.get("security"), dict) else {}
    llm_policy = evaluate_runtime_llm_policy(settings)
    llm = settings.get("llm", {}) if isinstance(settings.get("llm"), dict) else {}
    parsed_temperature = clamp_temperature(llm.get("temperature"), settings=settings)
    # Cord-cut aware: identical surface for the legacy Ollama client and the
    # gateway-backed client (any provider) — chosen by runtime_llm.client_backend.
    client = build_ollama_client()
    llm_runtime = _apply_ollama_boundary_status(
        build_ollama_boundary_runtime(client.base_url, client.chat_model, client.embedding_model)
        if is_ollama_runtime_probe_disabled()
        else client.get_runtime_diagnostics()
    )
    extra_runtime = {}
    return {
        "ok": bool(_STARTUP_STATE.get("ready")),
        "startup_ready": bool(_STARTUP_STATE.get("ready")),
        "startup_error": str(_STARTUP_STATE.get("error") or ""),
        "name": settings.get("project_name", "Sentinari"),
        "runtime_mode": runtime_mode,
        "interactive_enabled": runtime_mode != _RUNTIME_MODE_RUNTIME,
        "project_root": str(get_project_root()),
        "db_path": settings["paths"]["sqlite_db"],
        "taxonomy_root": settings["paths"]["taxonomy_root"],
        "auto_ingest_poll_seconds": _auto_ingest_service.poll_seconds,
        "auto_ingest_running": _auto_ingest_service.is_running(),
        "auto_ingest_policy_locked": bool(_is_runtime_mode(settings)),
        "admin_auth_enabled": bool(auth["enabled"]),
        "admin_auth_configured": bool(auth["configured"]),
        "admin_username": str(auth["username"]),
        "localhost_only": bool(security.get("localhost_only", True)),
        "interactive_api_admin_auth_required": bool(security.get("require_admin_auth_for_interactive_api", True)),
        "llm_firewall_ok": bool(llm_policy.get("ok")),
        "llm_firewall_violations": llm_policy.get("violations") or [],
        "llm_runtime": llm_runtime,
        "escalation_queue_enabled": False,
        "escalation_queue_autonomous_enabled": False,
        "escalation_queue_provider": "manual",
        "escalation_queue_queue_dir": "",
    }


@app.get("/api/runtime/profile")
def api_runtime_profile() -> dict[str, Any]:
    settings = get_settings()
    runtime_mode = _get_runtime_mode(settings)
    return {
        "ok": True,
        "runtime_mode": runtime_mode,
        "interactive_enabled": runtime_mode != _RUNTIME_MODE_RUNTIME,
        "compute_only": runtime_mode == _RUNTIME_MODE_RUNTIME,
        "runtime_allowed_paths": sorted(_RUNTIME_COMPUTE_ALLOWED_PATHS),
    }


@app.get("/ui/login", response_class=HTMLResponse)
def ui_login(next: str | None = Query(default="/ui/admin")) -> HTMLResponse:
    auth = get_admin_auth_settings(get_settings())
    next_path = _sanitize_next_path(next)
    if not auth["enabled"]:
        return HTMLResponse("", status_code=302, headers={"Location": next_path})
    return HTMLResponse(_build_login_page(next_path))


@app.get("/ui/admin", response_class=HTMLResponse)
def ui_admin(request: Request) -> HTMLResponse:
    auth = get_admin_auth_settings(get_settings())
    if auth["enabled"] and not _is_admin_authenticated(request):
        return HTMLResponse("", status_code=302, headers={"Location": "/ui/login?next=/ui/admin"})

    page = get_project_root() / "templates" / "admin_console.html"
    if not page.exists():
        raise HTTPException(status_code=500, detail="admin_console.html template not found.")
    return HTMLResponse(_inject_left_rail(page.read_text(encoding="utf-8"), active="/ui/admin"))


@app.get("/ui/start", response_class=HTMLResponse)
def ui_start(request: Request) -> HTMLResponse:
    auth = get_admin_auth_settings(get_settings())
    if auth["enabled"] and not _is_admin_authenticated(request):
        return HTMLResponse("", status_code=302, headers={"Location": "/ui/login?next=/ui/start"})

    page = get_project_root() / "templates" / "sentinari_start_console.html"
    if not page.exists():
        raise HTTPException(status_code=500, detail="sentinari_start_console.html template not found.")
    return HTMLResponse(page.read_text(encoding="utf-8"))


@app.get("/ui/playground", response_class=HTMLResponse)
def ui_playground(request: Request) -> HTMLResponse:
    auth = get_admin_auth_settings(get_settings())
    if auth["enabled"] and not _is_admin_authenticated(request):
        return HTMLResponse("", status_code=302, headers={"Location": "/ui/login?next=/ui/playground"})

    page = get_project_root() / "templates" / "playground_console.html"
    if not page.exists():
        raise HTTPException(status_code=500, detail="playground_console.html template not found.")
    return HTMLResponse(page.read_text(encoding="utf-8"))


@app.get("/ui/search", response_class=HTMLResponse)
def ui_search(request: Request) -> HTMLResponse:
    """Search workspace: the ingested library grouped by scientific area."""
    auth = get_admin_auth_settings(get_settings())
    if auth["enabled"] and not _is_admin_authenticated(request):
        return HTMLResponse("", status_code=302, headers={"Location": "/ui/login?next=/ui/search"})

    page = get_project_root() / "templates" / "search_workspace.html"
    if not page.exists():
        raise HTTPException(status_code=500, detail="search_workspace.html template not found.")
    return HTMLResponse(page.read_text(encoding="utf-8"))


@app.get("/ui/learning", response_class=HTMLResponse)
def ui_learning(request: Request) -> HTMLResponse:
    """Learning Index workspace: % Learned, exams, and calibration controls."""
    auth = get_admin_auth_settings(get_settings())
    if auth["enabled"] and not _is_admin_authenticated(request):
        return HTMLResponse("", status_code=302, headers={"Location": "/ui/login?next=/ui/learning"})

    page = get_project_root() / "templates" / "learning_workspace.html"
    if not page.exists():
        raise HTTPException(status_code=500, detail="learning_workspace.html template not found.")
    return HTMLResponse(page.read_text(encoding="utf-8"))


@app.get("/ui/patterns", response_class=HTMLResponse)
def ui_patterns(request: Request) -> HTMLResponse:
    auth = get_admin_auth_settings(get_settings())
    if auth["enabled"] and not _is_admin_authenticated(request):
        return HTMLResponse("", status_code=302, headers={"Location": "/ui/login?next=/ui/patterns"})

    page = get_project_root() / "templates" / "patterns_workspace.html"
    if not page.exists():
        raise HTTPException(status_code=500, detail="patterns_workspace.html template not found.")
    return HTMLResponse(page.read_text(encoding="utf-8"))


@app.get("/ui/qualia", response_class=HTMLResponse)
def ui_qualia(request: Request) -> HTMLResponse:
    return _render_authed_ui_template(
        request,
        template_name="qualia_console.html",
        next_path="/ui/qualia",
        missing_detail="qualia_console.html template not found.",
        left_rail=True,
    )


@app.get("/ui/gemma-qualia", response_class=HTMLResponse)
@app.get("/ui/SMI-qualia", response_class=HTMLResponse)
def ui_qualia_legacy_redirect(request: Request) -> HTMLResponse:
    """§45: legacy bookmarks keep working — they land on the canonical route."""
    return HTMLResponse("", status_code=307, headers={"Location": "/ui/qualia"})


@app.get("/ui/a1-logs", response_class=HTMLResponse)
def ui_a1_logs(request: Request) -> HTMLResponse:
    return _render_authed_ui_template(
        request,
        template_name="a1_logs_console.html",
        next_path="/ui/a1-logs",
        missing_detail="a1_logs_console.html template not found.",
    )


@app.get("/ui/direct", response_class=HTMLResponse)
def ui_direct(request: Request) -> HTMLResponse:
    return _render_authed_ui_template(
        request,
        template_name="direct_console.html",
        next_path="/ui/direct",
        missing_detail="direct_console.html template not found.",
        left_rail=True,
    )


@app.get("/ui/gemma-direct", response_class=HTMLResponse)
@app.get("/ui/SMI-direct", response_class=HTMLResponse)
def ui_direct_legacy_redirect(request: Request) -> HTMLResponse:
    """§45: legacy bookmarks keep working — they land on the canonical route."""
    return HTMLResponse("", status_code=307, headers={"Location": "/ui/direct"})


@app.get("/ui/victus", response_class=HTMLResponse)
def ui_victus(request: Request) -> HTMLResponse:
    return _render_authed_ui_template(
        request,
        template_name="victus_console.html",
        next_path="/ui/victus",
        missing_detail="victus_console.html template not found.",
    )


@app.get("/ui/model-lab", response_class=HTMLResponse)
def ui_model_lab(request: Request) -> HTMLResponse:
    return _render_authed_ui_template(
        request,
        template_name="model_deviation_lab.html",
        next_path="/ui/model-lab",
        missing_detail="model_deviation_lab.html template not found.",
        left_rail=True,
    )






def _render_authed_ui_template(
    request: Request,
    *,
    template_name: str,
    next_path: str,
    missing_detail: str,
    replacements: dict[str, str] | None = None,
    left_rail: bool = False,
) -> HTMLResponse:
    auth = get_admin_auth_settings(get_settings())
    if auth["enabled"] and not _is_admin_authenticated(request):
        return HTMLResponse("", status_code=302, headers={"Location": f"/ui/login?next={next_path}"})

    page = get_project_root() / "templates" / template_name
    if not page.exists():
        raise HTTPException(status_code=500, detail=missing_detail)

    try:
        html = page.read_text(encoding="utf-8-sig", errors="replace")
    except Exception:
        html = page.read_text(encoding="utf-8", errors="replace")

    for key, value in (replacements or {}).items():
        html = html.replace(key, value)
    if left_rail:
        html = _inject_left_rail(html, active=next_path)
    return HTMLResponse(html)


@app.get("/ui/playground/wan", response_class=HTMLResponse)
def ui_playground_wan(request: Request) -> HTMLResponse:
    return _render_authed_ui_template(
        request,
        template_name="wan_console.html",
        next_path="/ui/playground/wan",
        missing_detail="wan_console.html template not found.",
    )


@app.get("/ui/playground/workbench-a", response_class=HTMLResponse)
def ui_playground_workbench_a(request: Request) -> HTMLResponse:
    return _render_authed_ui_template(
        request,
        template_name="playground_workbench.html",
        next_path="/ui/playground/workbench-a",
        missing_detail="playground_workbench.html template not found.",
        replacements={
            "__WORKBENCH_TITLE__": "Sentinari Workbench A",
            "__WORKBENCH_SUBTITLE__": "Blank task sandbox for focused prompting, drafts, and execution planning.",
            "__WORKBENCH_STORAGE__": "workbench_a",
            "__WORKBENCH_PROMPT__": "Use this page for a dedicated task stream, prompt chain, or structured experiment.",
            "__WORKBENCH_A_ACTIVE__": "active",
            "__WORKBENCH_B_ACTIVE__": "",
        },
    )


@app.get("/ui/playground/workbench-b", response_class=HTMLResponse)
def ui_playground_workbench_b(request: Request) -> HTMLResponse:
    return _render_authed_ui_template(
        request,
        template_name="playground_workbench.html",
        next_path="/ui/playground/workbench-b",
        missing_detail="playground_workbench.html template not found.",
        replacements={
            "__WORKBENCH_TITLE__": "Sentinari Workbench B",
            "__WORKBENCH_SUBTITLE__": "Second blank sandbox for separate workflows, evaluations, or operator experiments.",
            "__WORKBENCH_STORAGE__": "workbench_b",
            "__WORKBENCH_PROMPT__": "Keep this page independent from Workbench A when you need a clean parallel track.",
            "__WORKBENCH_A_ACTIVE__": "",
            "__WORKBENCH_B_ACTIVE__": "active",
        },
    )


@app.get("/ui/chat", response_class=HTMLResponse)
def ui_chat(request: Request) -> HTMLResponse:
    auth = get_admin_auth_settings(get_settings())
    if auth["enabled"] and not _is_admin_authenticated(request):
        return HTMLResponse("", status_code=302, headers={"Location": "/ui/login?next=/ui/chat"})

    page = get_project_root() / "templates" / "chat_console.html"
    if not page.exists():
        raise HTTPException(status_code=500, detail="chat_console.html template not found.")
    return HTMLResponse(page.read_text(encoding="utf-8"))

@app.get("/api/admin/login-status")
def api_admin_login_status() -> dict[str, Any]:
    auth = get_admin_auth_settings(get_settings())
    return {
        "ok": True,
        "enabled": bool(auth["enabled"]),
        "configured": bool(auth["configured"]),
        "username": str(auth["username"]),
        "cookie_name": str(auth["session_cookie_name"]),
        "session_ttl_hours": int(auth["session_ttl_hours"]),
    }


@app.post("/api/admin/login")
def api_admin_login(payload: AdminLoginRequest, response: Response) -> dict[str, Any]:
    auth = get_admin_auth_settings(get_settings())
    if not auth["enabled"]:
        return {"ok": True, "enabled": False, "detail": "Sentinari admin login is disabled by configuration."}
    if not auth["configured"]:
        raise HTTPException(
            status_code=503,
            detail=(
                "Sentinari admin login is enabled but no password is configured. "
                "Set SENTINARI_ADMIN_PASSWORD (or configured password_env) before login."
            ),
        )

    username = (payload.username or "").strip()
    password = payload.password or ""
    if not verify_admin_credentials(username, password, auth):
        raise HTTPException(status_code=401, detail="Invalid admin username or password.")

    token, expires_at = create_admin_session_token(auth)
    ttl_seconds = int(auth["session_ttl_hours"]) * 3600
    response.set_cookie(
        key=str(auth["session_cookie_name"]),
        value=token,
        max_age=ttl_seconds,
        httponly=True,
        samesite="strict",
        secure=False,
        path="/",
    )
    expires_at_utc = datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()
    return {"ok": True, "enabled": True, "expires_at_utc": expires_at_utc}


@app.post("/api/admin/logout")
def api_admin_logout(response: Response) -> dict[str, Any]:
    auth = get_admin_auth_settings(get_settings())
    response.delete_cookie(key=str(auth["session_cookie_name"]), path="/")
    return {"ok": True}


@app.get("/api/admin/config")
def api_admin_config(_: None = Depends(_admin_auth_dependency)) -> dict[str, Any]:
    settings = get_settings()
    auth = get_admin_auth_settings(settings)
    llm_policy = evaluate_runtime_llm_policy(settings)
    with get_connection() as conn:
        live_operator_state = get_live_operator_state(conn)
        profile_snapshots = list_profile_snapshots(conn, limit=8)
    personality = (
        live_operator_state.get("personality", {})
        if isinstance(live_operator_state, dict) and isinstance(live_operator_state.get("personality"), dict)
        else settings.get("personality", {})
    )
    safety = (
        live_operator_state.get("safety", {})
        if isinstance(live_operator_state, dict) and isinstance(live_operator_state.get("safety"), dict)
        else settings.get("safety", {})
    )
    default_language = str(personality.get("default_language") or "English").strip() or "English"
    supported_languages = _normalize_languages(default_language, personality.get("supported_languages") or [])
    return {
        "ok": True,
        "config_path": str(get_config_path()),
        "sqlite_db_path": str(((settings.get("paths", {}) if isinstance(settings.get("paths", {}), dict) else {}).get("sqlite_db") or "")),
        "project_name": settings.get("project_name", "Sentinari"),
        "paths": settings.get("paths", {}),
        "ingestion": settings.get("ingestion", {}),
        "unsupervised": settings.get("unsupervised", {}),
        "runtime": settings.get("runtime", {}),
        "safety": safety,
        "security": {
            "admin_auth": {
                "enabled": bool(auth["enabled"]),
                "configured": bool(auth["configured"]),
                "username": str(auth["username"]),
                "session_cookie_name": str(auth["session_cookie_name"]),
                "session_ttl_hours": int(auth["session_ttl_hours"]),
            },
            "llm_firewall": llm_policy.get("firewall", {}),
            "llm_firewall_ok": bool(llm_policy.get("ok")),
            "llm_firewall_violations": llm_policy.get("violations") or [],
        },
        "personality": {
            "name": str(personality.get("name") or "Sentinari"),
            "tone": str(personality.get("tone") or ""),
            "purpose": str(personality.get("purpose") or ""),
            "default_language": default_language,
            "supported_languages": supported_languages,
            "domain_focus": str(personality.get("domain_focus") or ""),
            "out_of_scope_policy": str(personality.get("out_of_scope_policy") or ""),
            "goals": [str(g).strip() for g in (personality.get("goals") or []) if str(g).strip()],
            "general_addendum": str(personality.get("general_addendum") or ""),
            "coding_mode_system_addendum": str(personality.get("coding_mode_system_addendum") or ""),
        },
        "operator_state": live_operator_state or settings.get("_operator_state", {}),
        "profile_snapshots": profile_snapshots,
        "auto_ingest": {
            "running": _auto_ingest_service.is_running(),
            "poll_seconds": _auto_ingest_service.poll_seconds,
        },
    }


@app.post("/api/admin/personality")
def api_admin_personality(
    payload: PersonalityUpdateRequest,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    raw = load_raw_settings()
    personality = raw.setdefault("personality", {})
    if not isinstance(personality, dict):
        personality = {}
        raw["personality"] = personality

    name = (payload.name or "").strip() or "Sentinari"
    tone = (payload.tone or "").strip()
    purpose = (
        (payload.purpose or "").strip()
        or "Serve as a stable autonomous knowledge, reasoning, and pattern-recognition partner across the scientific fields."
    )
    default_language = (payload.default_language or "").strip() or "English"
    supported_languages = _normalize_languages(default_language, payload.supported_languages)
    domain_focus = (
        (payload.domain_focus or "").strip()
        or (
            "Scientific research across all fields, evidence-grounded knowledge work, "
            "and pattern recognition for societal problems."
        )
    )
    out_of_scope_policy = (
        (payload.out_of_scope_policy or "").strip()
        or (
            "Decline unsafe, illegal, or privacy-violating requests; redirect to "
            "scientific research and evidence-grounded knowledge tasks."
        )
    )
    goals = [str(g).strip() for g in (payload.goals or []) if str(g).strip()]
    general_addendum = (payload.general_addendum or "").strip()
    coding_addendum = (payload.coding_mode_system_addendum or "").strip()

    personality["name"] = name
    personality["tone"] = tone
    personality["purpose"] = purpose
    personality["default_language"] = default_language
    personality["supported_languages"] = supported_languages
    personality["domain_focus"] = domain_focus
    personality["out_of_scope_policy"] = out_of_scope_policy
    personality["goals"] = goals
    personality["general_addendum"] = general_addendum
    personality["coding_mode_system_addendum"] = coding_addendum

    path = save_raw_settings(raw)
    with get_connection() as conn:
        upsert_live_operator_state(conn, raw, source="personality_save")
        conn.commit()
    settings = reload_settings()
    with get_connection() as conn:
        snapshot_id = snapshot_profile_settings(conn, settings, source="personality_save")
        conn.commit()

    return {
        "ok": True,
        "saved_to": str(path),
        "snapshot_id": snapshot_id,
        "personality": settings.get("personality", {}),
    }


@app.post("/api/admin/safety")
def api_admin_safety(
    payload: SafetyUpdateRequest,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    raw = load_raw_settings()
    safety = raw.setdefault("safety", {})
    if not isinstance(safety, dict):
        safety = {}
        raw["safety"] = safety

    parameter_guardrails = safety.setdefault("parameter_guardrails", {})
    if not isinstance(parameter_guardrails, dict):
        parameter_guardrails = {}
        safety["parameter_guardrails"] = parameter_guardrails

    top_k_min = int(payload.top_k_min)
    top_k_max = int(payload.top_k_max)
    if top_k_max < top_k_min:
        top_k_max = top_k_min

    behavior_variant_min = float(payload.behavior_variant_min)
    behavior_variant_max = float(payload.behavior_variant_max)
    if behavior_variant_max < behavior_variant_min:
        behavior_variant_max = behavior_variant_min

    temperature_min = float(payload.temperature_min)
    temperature_max = float(payload.temperature_max)
    if temperature_max < temperature_min:
        temperature_max = temperature_min

    parameter_guardrails["top_k_min"] = top_k_min
    parameter_guardrails["top_k_max"] = top_k_max
    parameter_guardrails["behavior_variant_min"] = behavior_variant_min
    parameter_guardrails["behavior_variant_max"] = behavior_variant_max
    parameter_guardrails["temperature_min"] = temperature_min
    parameter_guardrails["temperature_max"] = temperature_max

    calm_mode = safety.setdefault("calm_mode", {})
    if not isinstance(calm_mode, dict):
        calm_mode = {}
        safety["calm_mode"] = calm_mode
    calm_mode["enabled"] = bool(payload.calm_mode_enabled)

    raw_keywords = payload.anxiety_keywords or []
    normalized_keywords: list[str] = []
    seen_keywords: set[str] = set()
    for item in raw_keywords:
        keyword = str(item or "").strip().lower()
        if not keyword:
            continue
        if keyword in seen_keywords:
            continue
        normalized_keywords.append(keyword)
        seen_keywords.add(keyword)
    if not normalized_keywords:
        normalized_keywords = ["anxiety", "panic", "overwhelmed", "unsafe", "afraid", "stressed"]
    calm_mode["anxiety_keywords"] = normalized_keywords

    ethics = safety.setdefault("ethics", {})
    if not isinstance(ethics, dict):
        ethics = {}
        safety["ethics"] = ethics
    ethics["enforce_safe_completions"] = bool(payload.enforce_safe_completions)
    ethics["refuse_harmful_or_illegal"] = bool(payload.refuse_harmful_or_illegal)
    ethics["privacy_first"] = bool(payload.privacy_first)

    path = save_raw_settings(raw)
    with get_connection() as conn:
        upsert_live_operator_state(conn, raw, source="safety_save")
        conn.commit()
    settings = reload_settings()
    with get_connection() as conn:
        snapshot_id = snapshot_profile_settings(conn, settings, source="safety_save")
        conn.commit()

    return {
        "ok": True,
        "saved_to": str(path),
        "snapshot_id": snapshot_id,
        "safety": settings.get("safety", {}),
    }


@app.get("/api/admin/profile/snapshots")
def api_admin_profile_snapshots(
    limit: int = Query(default=12, ge=1, le=100),
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    with get_connection() as conn:
        items = list_profile_snapshots(conn, limit=limit)
    return {"ok": True, "count": len(items), "items": items}


def _field_label_matches(label: str, aliases: list[str]) -> bool:
    text = str(label or "").lower()
    return any(str(alias or "").lower() in text for alias in aliases if str(alias or "").strip())


def _aggregate_learning_labels(conn: sqlite3.Connection, table_name: str) -> list[dict[str, Any]]:
    if table_name == "documents":
        rows = conn.execute(
            """
            SELECT
                COALESCE(scientific_field, '') AS scientific_field,
                COALESCE(vocational_discipline, '') AS vocational_discipline,
                COALESCE(source_collection, '') AS source_collection,
                COUNT(*) AS c
            FROM documents
            GROUP BY scientific_field, vocational_discipline, source_collection;
            """
        ).fetchall()
    else:
        rows = conn.execute(
            f"""
            SELECT
                COALESCE(d.scientific_field, '') AS scientific_field,
                COALESCE(d.vocational_discipline, '') AS vocational_discipline,
                COALESCE(d.source_collection, '') AS source_collection,
                COUNT(*) AS c
            FROM {table_name} s
            LEFT JOIN documents d ON d.id = s.document_id
            GROUP BY d.scientific_field, d.vocational_discipline, d.source_collection;
            """
        ).fetchall()
    return [
        {
            "label": " ".join(
                str(row[key] or "")
                for key in ("scientific_field", "vocational_discipline", "source_collection")
            ),
            "count": int(row["c"] or 0),
        }
        for row in rows
    ]


def _sum_matching(aggregates: list[dict[str, Any]], aliases: list[str]) -> int:
    return sum(int(item.get("count") or 0) for item in aggregates if _field_label_matches(str(item.get("label") or ""), aliases))


def _learning_field_count(
    field_name: str,
    aliases: list[str],
    *,
    document_aggregates: list[dict[str, Any]],
) -> dict[str, Any]:
    all_aliases = [field_name, *aliases]
    document_count = _sum_matching(document_aggregates, all_aliases)
    seeded_quantity = document_count
    target_quantity = max(250, min(5000, 250 + (document_count * 2)))
    coverage = round(min(100.0, (seeded_quantity / target_quantity) * 100.0), 1) if target_quantity else 0.0
    return {
        "field": field_name,
        "aliases": aliases,
        "documents": document_count,
        "seeded_quantity": seeded_quantity,
        "target_quantity": target_quantity,
        "coverage": coverage,
        "status": "seeded" if seeded_quantity else "needs_source",
    }


@app.get("/api/admin/learning-fields")
def api_admin_learning_fields(_: None = Depends(_admin_auth_dependency)) -> dict[str, Any]:
    desired_fields = [
        ("Scientific Method", ["scientific method", "hypothesis", "empiricism", "peer review"]),
        ("Mathematics", ["mathematics", "math", "statistics", "linear algebra", "calculus"]),
        ("Physics", ["physics", "quantum"]),
        ("Chemistry", ["chemistry", "chemical"]),
        ("Biology", ["biology", "ecology", "life sciences"]),
        ("Psychology", ["psychology", "cognitive", "behaviour", "behavior"]),
        ("Sociology / Humanistics", ["sociology", "humanities", "humanistics", "social"]),
        ("Artificial Intelligence", ["artificial intelligence", "machine learning", "ai", "llm"]),
        ("Data Integrity", ["data integrity", "provenance", "verification", "synthetic", "audit"]),
    ]
    with get_connection() as conn:
        document_aggregates = _aggregate_learning_labels(conn, "documents")
        fields = [
            _learning_field_count(
                name,
                aliases,
                document_aggregates=document_aggregates,
            )
            for name, aliases in desired_fields
        ]
        totals = {
            "documents": int(conn.execute("SELECT COUNT(*) AS c FROM documents;").fetchone()["c"]),
        }
    totals["seeded_quantity"] = totals["documents"]
    return {
        "ok": True,
        "fields": fields,
        "totals": totals,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


@app.get("/api/admin/tasks")
def api_admin_tasks(
    limit: int = Query(default=100, ge=1, le=300),
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    with get_connection() as conn:
        items = list_tasks(conn, limit=limit)
    return {"ok": True, "count": len(items), "items": items}


@app.get("/api/admin/service-logs")
def api_admin_service_logs(_: None = Depends(_admin_auth_dependency)) -> dict[str, Any]:
    log_root = (get_project_root() / "data" / "logs").resolve()
    stdout_log = _tail_text_file(log_root / "sentinari.stdout.log")
    stderr_log = _tail_text_file(log_root / "sentinari.stderr.log")
    return {
        "ok": True,
        "log_root": str(log_root),
        "stdout": stdout_log,
        "stderr": stderr_log,
        "refreshed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


@app.post("/api/admin/tasks")
def api_admin_tasks_create(
    payload: TaskCreateRequest,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    with get_connection() as conn:
        item = create_task(
            conn,
            task_to_perform=payload.task_to_perform,
            target_datetime=payload.target_datetime,
            quality_standard_expected=payload.quality_standard_expected,
            knowledge_library_applicable=payload.knowledge_library_applicable,
            smi_feedback=payload.smi_feedback,
            evaluation=payload.evaluation,
            status=payload.status,
        )
        conn.commit()
    return {"ok": True, "task": item}


@app.put("/api/admin/tasks/{task_id}")
def api_admin_tasks_update(
    task_id: int,
    payload: TaskUpdateRequest,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    with get_connection() as conn:
        item = update_task(
            conn,
            task_id=task_id,
            task_to_perform=payload.task_to_perform,
            target_datetime=payload.target_datetime,
            quality_standard_expected=payload.quality_standard_expected,
            knowledge_library_applicable=payload.knowledge_library_applicable,
            smi_feedback=payload.smi_feedback,
            evaluation=payload.evaluation,
            status=payload.status,
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        conn.commit()
    return {"ok": True, "task": item}


@app.post("/api/admin/tasks/{task_id}/ask-sentinari")
def api_admin_tasks_ask_sentinari(
    task_id: int,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    with get_connection() as conn:
        task = get_task(conn, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")

    result = run_chat(
        message=build_task_prompt(task),
        mode="knowledge",
        session_id=f"task-{task_id}",
        top_k=6,
        behavior_variant=0.1,
        use_web_fetch=False,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Task guidance failed.")

    feedback = str(result.get("answer") or "").strip()
    next_status = "in_progress" if str(task.get("status") or "pending") == "pending" else str(task.get("status") or "pending")
    with get_connection() as conn:
        item = update_task_feedback(conn, task_id=task_id, smi_feedback=feedback, status=next_status)
        conn.commit()
    return {
        "ok": True,
        "task": item,
        "answer": feedback,
        "session_id": str(result.get("session_id") or f"task-{task_id}"),
        "citations": result.get("citations") or [],
    }


@app.get("/api/admin/auto-ingest")
def api_admin_auto_ingest(_: None = Depends(_admin_auth_dependency)) -> dict[str, Any]:
    return {
        "ok": True,
        "running": _auto_ingest_service.is_running(),
        "poll_seconds": _auto_ingest_service.poll_seconds,
    }


@app.post("/api/admin/auto-ingest/start")
def api_admin_auto_ingest_start(_: None = Depends(_admin_auth_dependency)) -> dict[str, Any]:
    _auto_ingest_service.start()
    return {
        "ok": True,
        "running": _auto_ingest_service.is_running(),
        "poll_seconds": _auto_ingest_service.poll_seconds,
    }


@app.post("/api/admin/auto-ingest/stop")
def api_admin_auto_ingest_stop(_: None = Depends(_admin_auth_dependency)) -> dict[str, Any]:
    _auto_ingest_service.stop()
    return {
        "ok": True,
        "running": _auto_ingest_service.is_running(),
        "poll_seconds": _auto_ingest_service.poll_seconds,
    }


@app.get("/api/playground/config")
def api_playground_config(_: None = Depends(_admin_auth_dependency)) -> dict[str, Any]:
    data = get_playground_config()
    openalex = _read_openalex_manifest()
    data["openalex_enabled"] = bool(openalex.get("openalex_enabled", True))
    data["openalex_manifest_path"] = str(_OPENALEX_MANIFEST_PATH)
    return data


@app.post("/api/playground/sentinel/policy/reload")
def api_playground_sentinel_policy_reload(_: None = Depends(_admin_auth_dependency)) -> dict[str, Any]:
    from .sentinel_firewall import firewall

    policy = firewall.reload_policy()
    return {"ok": True, "policy": policy, "recent_refusals": firewall.recent_refusals(limit=10)}




@app.post("/api/playground/openalex")
def api_playground_openalex(
    payload: OpenAlexToggleRequest,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    saved_to = _write_openalex_manifest(payload.enabled)
    return {
        "ok": True,
        "saved_to": str(saved_to),
        "openalex_enabled": bool(payload.enabled),
    }


@app.get("/api/playground/library-progress")
def api_playground_library_progress(_: None = Depends(_admin_auth_dependency)) -> dict[str, Any]:
    return get_learning_library_progress()


@app.get("/api/skills/status")
def api_skills_status(_: None = Depends(_admin_auth_dependency)) -> dict[str, Any]:
    skills = load_skill_index()
    return {
        "ok": True,
        "skills_root": str(get_skills_root()),
        "skill_count": len(skills),
        "chunk_count": sum(int(item.get("chunk_count") or 0) for item in skills),
        "last_skill": str(skills[-1].get("name") or "") if skills else "",
        "skills_fallback_enabled": not is_fallback_disabled(),
        "skills": skills,
    }


@app.post("/api/skills/upload")
async def api_skills_upload(
    skill_name: str = Form(default="", max_length=80),
    files: list[UploadFile] = File(...),
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one skill file.")
    if len(files) > 20:
        raise HTTPException(status_code=400, detail="Upload up to 20 skill files at a time.")

    name = sanitize_skill_name(skill_name)
    skill_dir = get_skills_root() / name
    skill_dir.mkdir(parents=True, exist_ok=True)

    stored: list[dict[str, Any]] = []
    description = ""
    for upload in files:
        original_name = str(upload.filename or "").strip() or "skill-file.bin"
        safe_name = sanitize_chat_upload_filename(original_name)
        target = skill_dir / safe_name
        counter = 1
        while target.exists():
            target = skill_dir / f"{Path(safe_name).stem}-{counter}{Path(safe_name).suffix}"
            counter += 1
        written = 0
        try:
            with target.open("wb") as handle:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > 100 * 1024 * 1024:
                        raise ValueError(f"{original_name} exceeds the 100 MB skill file limit.")
                    handle.write(chunk)
            if written <= 0:
                raise ValueError(f"{original_name} is empty.")
            stored.append({"name": target.name, "path": str(target), "bytes": written})
        except Exception as ex:
            try:
                if target.exists():
                    target.unlink()
            except Exception:
                pass
            raise HTTPException(status_code=400, detail=f"{original_name}: {ex}") from ex
        finally:
            await upload.close()

        if not description:
            try:
                first_line = target.read_text(encoding="utf-8", errors="ignore").splitlines()
                for line in first_line[:3]:
                    candidate = line.strip()
                    if candidate:
                        description = candidate[:200]
                        break
            except Exception:
                description = ""

    result = ingest_files(
        [item["path"] for item in stored],
        metadata={
            "scientific_field": "computer-and-information-sciences",
            "vocational_discipline": "software-engineering",
            "source_collection": "SMi Skills",
            "module": "uploaded-skill",
            "topic": f"skill-{name}",
            "priority": 180,
            "domain": "smi-skills",
            "publisher": "SMi Skills Manager",
            "license": "operator-provided",
            "extra_metadata": {"smi_skill": name, "source_lane": "skills"},
        },
        allow_embeddings=False,
    )
    chunk_count = sum(
        int(item.get("chunk_count") or 0)
        for item in result.get("items") or []
        if item.get("ok")
    )
    entry = register_skill(name=name, files=stored, chunk_count=chunk_count, description=description)
    return {
        "ok": True,
        "skill": name,
        "description": entry.get("description") or "",
        "accepted": len(stored),
        "chunk_count": chunk_count,
        "skills_root": str(get_skills_root()),
        "items": result.get("items") or [],
    }


@app.post("/api/skills/fallback")
def api_skills_fallback(
    payload: dict[str, Any],
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    result = set_fallback_enabled(bool(payload.get("enabled", True)))
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=str(result.get("error") or "Could not update fallback flag."))
    return result




@app.get("/api/playground/personal-growth/status")
def api_playground_personal_growth_status(_: None = Depends(_admin_auth_dependency)) -> dict[str, Any]:
    return personal_growth_status()


@app.get("/api/playground/personal-growth/finetune/status")
def api_playground_personal_growth_finetune_status(
    run_id: str | None = Query(default=None, max_length=120),
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    return personal_growth_finetune_status(run_id=run_id)


@app.post("/api/playground/personal-growth/finetune/dataset")
def api_playground_personal_growth_finetune_dataset(
    payload: dict[str, Any],
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    categories = payload.get("categories")
    if isinstance(categories, str):
        categories = [item.strip() for item in categories.replace(";", ",").split(",") if item.strip()]
    if not isinstance(categories, list):
        categories = []
    try:
        return create_personal_growth_finetune_dataset(
            categories=[str(item or "").strip() for item in categories if str(item or "").strip()],
            model_name=str(payload.get("model_name") or "gemma4:12B").strip() or "gemma4:12B",
            max_samples=int(payload.get("max_samples") or 2000),
            sample_style=str(payload.get("sample_style") or "source_grounded").strip() or "source_grounded",
        )
    except sqlite3.OperationalError as ex:
        if "locked" not in str(ex).lower():
            raise
        raise HTTPException(status_code=409, detail="Personal growth DB is busy. Try again shortly.")


@app.post("/api/playground/personal-growth/upload")
async def api_playground_personal_growth_upload(
    files: list[UploadFile] = File(...),
    category: str = Form(default="humanities-and-development", max_length=120),
    purpose: str = Form(default="", max_length=500),
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    if not files:
        raise HTTPException(status_code=400, detail="At least one personal-growth file is required.")
    if len(files) > 20:
        raise HTTPException(status_code=400, detail="Upload up to 20 personal-growth files at a time.")

    settings = get_settings()
    max_size_mb = max(1, min(200, int(settings.get("ingestion", {}).get("auto_max_file_size_mb") or 30)))
    max_bytes = max_size_mb * 1024 * 1024
    clean_category = str(category or "humanities-and-development").strip() or "humanities-and-development"
    clean_purpose = str(purpose or "").strip()
    target_dir = (get_project_root() / "data" / "personal_growth_uploads" / _safe_upload_segment(clean_category, "general")).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    stored_paths: list[str] = []
    items: list[dict[str, Any]] = []
    for upload in files:
        original_name = str(upload.filename or "").strip() or "upload.bin"
        safe_name = sanitize_chat_upload_filename(original_name)
        target = target_dir / safe_name
        counter = 1
        while target.exists():
            stem = Path(safe_name).stem
            suffix = Path(safe_name).suffix
            target = target_dir / f"{stem}-{counter}{suffix}"
            counter += 1

        written = 0
        try:
            with target.open("wb") as handle:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_bytes:
                        raise ValueError(f"{original_name} exceeds the {max_size_mb} MB upload limit.")
                    handle.write(chunk)
            if written <= 0:
                raise ValueError(f"{original_name} is empty.")
            stored_paths.append(str(target))
            items.append(
                {
                    "original_name": original_name,
                    "stored_name": target.name,
                    "stored_path": str(target),
                    "bytes": written,
                    "uploaded": True,
                    "ingest_ok": False,
                }
            )
        except Exception as ex:
            try:
                if target.exists():
                    target.unlink()
            except Exception:
                pass
            items.append(
                {
                    "original_name": original_name,
                    "stored_name": "",
                    "stored_path": "",
                    "bytes": written,
                    "uploaded": False,
                    "ingest_ok": False,
                    "error": str(ex),
                }
            )
        finally:
            await upload.close()

    if not stored_paths:
        first_error = next((str(item.get("error") or "") for item in items if item.get("error")), "")
        raise HTTPException(status_code=400, detail=first_error or "No personal-growth files were accepted.")

    ingested = 0
    failed = 0
    by_path = {str(item.get("stored_path") or ""): item for item in items}
    for path in stored_paths:
        item = by_path.get(path)
        try:
            if is_personal_growth_media_file(path):
                result = register_personal_growth_media(path, category=clean_category, purpose=clean_purpose)
            else:
                result = ingest_personal_growth_file(path, category=clean_category, purpose=clean_purpose)
            ingested += 1
            if item is not None:
                item.update(
                    {
                        "ingest_ok": True,
                        "document_id": result.get("document_id"),
                        "asset_id": result.get("asset_id"),
                        "source_id": result.get("source_id") or result.get("media_id"),
                        "title": result.get("title"),
                        "media_type": result.get("media_type", ""),
                        "chunk_count": result.get("chunk_count"),
                        "char_count": result.get("char_count"),
                        "analysis_status": result.get("analysis_status", ""),
                    }
                )
        except Exception as ex:
            failed += 1
            record_personal_growth_failure(path, error=str(ex), category=clean_category, purpose=clean_purpose)
            if item is not None:
                item["error"] = str(ex)

    if ingested <= 0:
        first_error = next((str(item.get("error") or "") for item in items if item.get("error")), "")
        raise HTTPException(status_code=400, detail=first_error or "No personal-growth documents were ingested.")

    status = personal_growth_status()
    return {
        "ok": True,
        "storage_lane": "smi_personal_growth",
        "db_path": status.get("db_path"),
        "upload_dir": str(target_dir),
        "category": clean_category,
        "purpose": clean_purpose,
        "uploaded": len(stored_paths),
        "ingested": ingested,
        "failed": failed,
        "items": items,
        "status": status,
    }


# ---------------------------------------------------------------------------
# Sentinel Domains: scientific fields that feed gemma4:12B
# ---------------------------------------------------------------------------


@app.get("/api/playground/sentinel/status")
def api_playground_sentinel_status(_: None = Depends(_admin_auth_dependency)) -> dict[str, Any]:
    return get_sentinel_status(refresh_counts=False)


@app.post("/api/playground/sentinel/ensure")
def api_playground_sentinel_ensure(_: None = Depends(_admin_auth_dependency)) -> dict[str, Any]:
    return ensure_sentinel_database()


@app.post("/api/playground/sentinel/upload")
async def api_playground_sentinel_upload(
    field: str = Form(..., max_length=120),
    files: list[UploadFile] = File(...),
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one PDF or document.")
    if len(files) > SENTINEL_MAX_UPLOAD_FILES:
        raise HTTPException(status_code=400, detail=f"Upload up to {SENTINEL_MAX_UPLOAD_FILES} files at a time.")

    settings = get_settings()
    max_size_mb = SENTINEL_DOC_MAX_MB
    max_bytes = max_size_mb * 1024 * 1024
    pdf_max_bytes = SENTINEL_PDF_MAX_MB * 1024 * 1024
    target_dir = (get_project_root() / "data" / "sentinel_uploads" / _safe_upload_segment(field, "field")).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    items: list[dict[str, Any]] = []
    stored_paths: list[str] = []
    for upload in files:
        original_name = str(upload.filename or "").strip() or "upload.bin"
        safe_name = sanitize_chat_upload_filename(original_name)
        target = target_dir / safe_name
        counter = 1
        while target.exists():
            target = target_dir / f"{Path(safe_name).stem}-{counter}{Path(safe_name).suffix}"
            counter += 1
        written = 0
        is_pdf = original_name.lower().endswith(".pdf")
        effective_limit = pdf_max_bytes if is_pdf else max_bytes
        effective_limit_mb = SENTINEL_PDF_MAX_MB if is_pdf else max_size_mb
        try:
            with target.open("wb") as handle:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > effective_limit:
                        raise ValueError(f"{original_name} exceeds the {effective_limit_mb} MB upload limit.")
                    handle.write(chunk)
            if written <= 0:
                raise ValueError(f"{original_name} is empty.")
            stored_paths.append(str(target))
            items.append({"ok": True, "original_name": original_name, "stored_path": str(target), "bytes": written})
        except Exception as ex:
            items.append({"ok": False, "original_name": original_name, "error": str(ex)})
        finally:
            await upload.close()

    if not stored_paths:
        raise HTTPException(status_code=400, detail="No uploaded Sentinel documents were accepted.")

    result = ingest_sentinel_field_files(
        field,
        stored_paths,
        module="uploaded-document",
        topic="sentinel-upload",
    )
    result["accepted"] = items
    result["uploaded_bytes"] = sum(int(item.get("bytes") or 0) for item in items if item.get("ok"))
    return result


@app.post("/api/playground/sentinel/github")
def api_playground_sentinel_github(
    payload: dict[str, Any],
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    field = str(payload.get("field") or "").strip()
    if not field:
        raise HTTPException(status_code=400, detail="A Sentinel scientific field is required.")
    urls = payload.get("urls")
    if isinstance(urls, str):
        urls = [line.strip() for line in urls.replace(",", "\n").splitlines() if line.strip()]
    if not isinstance(urls, list) or not urls:
        raise HTTPException(status_code=400, detail="Provide at least one GitHub repository URL.")
    try:
        requested_files = int(payload.get("max_files_per_repo") or 200)
        requested_mb = float(payload.get("max_total_mb") or 300)
        return ingest_github_dataset_to_field(
            field,
            [str(url or "").strip() for url in urls if str(url or "").strip()],
            max_files_per_repo=max(1, min(SENTINEL_GITHUB_MAX_FILES, requested_files)),
            max_total_mb=max(1.0, min(300.0, requested_mb)),
        )
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@app.post("/api/playground/sentinel/huggingface")
def api_playground_sentinel_huggingface(
    payload: dict[str, Any],
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    field = str(payload.get("field") or "").strip()
    if not field:
        raise HTTPException(status_code=400, detail="A Sentinel scientific field is required.")
    dataset = str(payload.get("dataset") or "").strip()
    if not dataset:
        raise HTTPException(status_code=400, detail="Provide a Hugging Face dataset name.")
    try:
        return ingest_huggingface_dataset_to_field(
            field,
            dataset,
            config_name=str(payload.get("config_name") or "default"),
            split=str(payload.get("split") or "train"),
            rows=int(payload.get("rows") or 50),
        )
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@app.get("/api/playground/sentinel/github/inspect")
def api_playground_sentinel_github_inspect(
    url: str = Query(default="", max_length=500),
    max_files: int = Query(default=100),
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    if not url.strip():
        raise HTTPException(status_code=400, detail="Provide a GitHub repository URL.")
    try:
        return list_github_dataset_files(url.strip(), max_files=max(1, min(SENTINEL_GITHUB_MAX_FILES, max_files)))
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@app.post("/api/playground/sentinel/field/clear")
def api_playground_sentinel_field_clear(
    payload: dict[str, Any],
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    field = str(payload.get("field") or "").strip()
    if not field:
        raise HTTPException(status_code=400, detail="A Sentinel scientific field is required.")
    purge_db = bool(payload.get("purge_database", False))
    try:
        return remove_sentinel_field_data(field, purge_database=purge_db)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@app.post("/api/playground/coding-corpus/sync")
def api_playground_coding_corpus_sync(
    force: bool = Query(default=False),
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    result = sync_coding_corpus(force=force)
    result["coding_corpus"] = get_coding_corpus_progress()
    return result


@app.post("/api/playground/qualia/benchmark")
def api_playground_qualia_benchmark(
    payload: PlaygroundQualiaBenchmarkRequest,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    before_baseline = get_playground_config().get("benchmark_baseline") or {}
    result = run_qualia_benchmark(
        prompts=payload.prompts,
        top_k=payload.top_k,
        apply_baseline=bool(payload.apply_baseline),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Qualia benchmark failed.")
    winner_row = result.get("winner") if isinstance(result.get("winner"), dict) else {}
    winner = winner_row.get("candidate") if isinstance(winner_row.get("candidate"), dict) else {}
    average_scores = winner_row.get("average_scores") if isinstance(winner_row.get("average_scores"), dict) else {}
    saved = result.get("saved") if isinstance(result.get("saved"), dict) else {}
    after_baseline = (
        saved.get("benchmark_baseline")
        if isinstance(saved.get("benchmark_baseline"), dict)
        else {
            "behavior_variant": _optional_float(winner.get("behavior_variant")),
            "gamma": _optional_float(winner.get("gamma")),
            "stability_bias": _optional_float(winner.get("stability_bias")),
            "top_k": int(result.get("top_k") or payload.top_k),
        }
    )
    benchmark_summary = {
        "prompt_count": int(result.get("prompt_count") or 0),
        "candidate_count": int(result.get("candidate_count") or 0),
        "winner": winner_row,
        "baseline_saved": bool(result.get("baseline_saved")),
        "saved": saved,
        "candidates": result.get("candidates") if isinstance(result.get("candidates"), list) else [],
    }
    before_state = {
        "behavior_variant": _optional_float(before_baseline.get("behavior_variant")),
        "gamma": _optional_float(before_baseline.get("gamma")),
        "stability_bias": _optional_float(before_baseline.get("stability_bias")),
        "top_k": before_baseline.get("top_k"),
        "baseline": before_baseline,
    }
    after_state = {
        "behavior_variant": _optional_float(after_baseline.get("behavior_variant")),
        "gamma": _optional_float(after_baseline.get("gamma")),
        "stability_bias": _optional_float(after_baseline.get("stability_bias")),
        "top_k": after_baseline.get("top_k"),
        "baseline": after_baseline,
        "winner": winner,
        "average_scores": average_scores,
        "baseline_saved": bool(result.get("baseline_saved")),
    }
    with get_connection() as conn:
        history_entry_id = record_qualia_history(
            conn,
            run_type="benchmark",
            source="playground_api",
            behavior_variant=_optional_float(after_baseline.get("behavior_variant")),
            gamma_requested=_optional_float(after_baseline.get("gamma")),
            gamma_effective=_optional_float(after_baseline.get("gamma")),
            stability_bias=_optional_float(after_baseline.get("stability_bias")),
            attention_score=_optional_float(average_scores.get("attention")),
            reasoning_score=_optional_float(average_scores.get("reasoning")),
            logic_score=_optional_float(average_scores.get("logic")),
            confidence=_optional_float(average_scores.get("overall")),
            before_state=before_state,
            after_state=after_state,
            benchmark_summary=benchmark_summary,
        )
        conn.commit()
    result["history_entry_id"] = history_entry_id
    return result


@app.post("/api/playground/qualia/recommend")
def api_playground_qualia_recommend(
    payload: QualiaRecommendationRequest,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    recommendation = build_qualia_recommendation(
        question=payload.question,
        answer=payload.answer,
        citations=payload.citations,
        qualia=payload.qualia,
        current_variant=payload.behavior_variant,
        current_gamma=payload.current_gamma,
        current_stability_bias=payload.current_stability_bias,
        gamma_cap=payload.gamma_cap,
        settings=get_settings(),
    )
    qualia = payload.qualia if isinstance(payload.qualia, dict) else {}
    summary = qualia.get("summary") if isinstance(qualia.get("summary"), dict) else {}
    focus_scores = recommendation.get("focus_scores") if isinstance(recommendation.get("focus_scores"), dict) else {}
    before_state = {
        "behavior_variant": float(payload.behavior_variant),
        "gamma": float(payload.current_gamma),
        "stability_bias": float(payload.current_stability_bias),
        "gamma_cap": float(payload.gamma_cap),
    }
    after_state = {
        "behavior_variant": _optional_float(recommendation.get("variant")),
        "gamma": _optional_float(recommendation.get("gamma")),
        "stability_bias": _optional_float(recommendation.get("stability_bias")),
        "delta": _optional_float(recommendation.get("delta")),
        "should_apply": bool(recommendation.get("should_apply")),
    }
    with get_connection() as conn:
        history_entry_id = record_qualia_history(
            conn,
            run_type="recommendation",
            source="playground_api",
            session_id=str(payload.session_id or ""),
            behavior_variant=float(payload.behavior_variant),
            effective_variant_ratio=_optional_float(qualia.get("effective_variant_ratio")),
            gamma_requested=float(payload.current_gamma),
            gamma_effective=_optional_float(qualia.get("gamma_effective")),
            stability_bias=float(payload.current_stability_bias),
            stability_index=_optional_float(qualia.get("stability_index")),
            influence=_optional_float(qualia.get("influence")),
            attention_score=_optional_float(focus_scores.get("attention")),
            reasoning_score=_optional_float(focus_scores.get("reasoning")),
            logic_score=_optional_float(focus_scores.get("logic")),
            confidence=_optional_float(recommendation.get("confidence")),
            before_state=before_state,
            after_state=after_state,
            recommendation=recommendation,
            bell_curve=qualia.get("bell_curve") if isinstance(qualia.get("bell_curve"), dict) else {},
            trajectory=qualia.get("trajectory") if isinstance(qualia.get("trajectory"), list) else [],
            benchmark_summary={"qualia_summary": summary} if summary else {},
        )
        conn.commit()
    return {"ok": True, "recommendation": recommendation, "history_entry_id": history_entry_id}


@app.get("/api/playground/vault/status")
def api_playground_vault_status(
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    """Qualia math status: always live from plaintext modules (vault removed)."""
    modules = [name.replace("app.", "") for name in ("app.qualia", "app.qualia_recommendation")]
    modules_live = all(name in sys.modules for name in ("app.qualia", "app.qualia_recommendation"))
    return {
        "ok": True,
        "vault_present": False,
        "unlocked": True,
        "modules_live": modules_live,
        "modules": modules,
        "instruction": "",
    }


@app.get("/api/playground/qualia/history")
def api_playground_qualia_history(
    limit: int = Query(default=40, ge=1, le=200),
    run_type: str = Query(default=""),
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    normalized_type = str(run_type or "").strip().lower()
    fetch_limit = limit if not normalized_type else min(300, max(limit * 3, limit))
    with get_connection() as conn:
        items = list_qualia_history(conn, limit=fetch_limit)
    if normalized_type:
        items = [item for item in items if str(item.get("run_type") or "").lower() == normalized_type][:limit]
    else:
        items = items[:limit]
    return {"ok": True, "count": len(items), "items": items}


@app.post("/api/qualia/forensic-audit")
def api_qualia_forensic_audit(
    payload: ForensicAuditRequest,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    """Execute Dr. Wepener's Forensic Governance & Courtroom Deception Audit."""
    audit = generate_merciless_audit_report(
        source_text=payload.source_text,
        source_title=payload.source_title,
        domain=payload.domain,
    )
    with get_connection() as conn:
        row_id = persist_forensic_audit(conn, audit, payload.source_text)
    audit["row_id"] = row_id
    return {"ok": True, "audit": audit}


@app.get("/api/qualia/forensic-audit/exemplars")
def api_qualia_forensic_exemplars() -> dict[str, Any]:
    """Return pre-loaded high-priority governance cross-examination exemplars."""
    return {"ok": True, "exemplars": EXEMPLARS}


@app.get("/api/qualia/forensic-audit/history")
def api_qualia_forensic_history(
    limit: int = Query(default=20, ge=1, le=100),
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    """Retrieve logged, stamped forensic governance audits."""
    with get_connection() as conn:
        audits = list_forensic_audits(conn, limit=limit)
    return {"ok": True, "count": len(audits), "audits": audits}


@app.get("/api/qualia/forensic-audit/{audit_ref}/report", response_class=HTMLResponse)
def api_qualia_forensic_report_html(
    audit_ref: str,
) -> HTMLResponse:
    """Render a standalone, print-optimized 1-page A4 Merciless Forensic Audit sheet."""
    with get_connection() as conn:
        audit = get_forensic_audit_by_ref(conn, audit_ref)
    if not audit:
        raise HTTPException(status_code=404, detail="Forensic audit reference not found.")
    html = render_standalone_audit_html(audit)
    return HTMLResponse(content=html, status_code=200)


@app.get("/api/playground/video/status")
def api_playground_video_status(_: None = Depends(_admin_auth_dependency)) -> dict[str, Any]:
    return get_video_lab_status()


@app.get("/api/playground/video/wan-status")
def api_playground_video_wan_status(_: None = Depends(_admin_auth_dependency)) -> dict[str, Any]:
    return get_wan_video_status()


@app.post("/api/playground/video/plan")
def api_playground_video_plan(
    payload: PlaygroundVideoPlanRequest,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    try:
        plan = build_plan_from_prompt(
            prompt=payload.prompt,
            language=payload.language,
            fps=payload.fps,
            max_scenes=payload.max_scenes,
        )
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    return {"ok": True, "plan": plan}


@app.post("/api/playground/video/render")
def api_playground_video_render(
    payload: PlaygroundVideoRenderRequest,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    if not payload.scenes:
        raise HTTPException(status_code=400, detail="At least one scene is required.")
    try:
        plan = {
            "language": payload.language,
            "fps": payload.fps,
            "scenes": [scene.model_dump() for scene in payload.scenes],
        }
        return render_text_plan(plan, filename_hint=payload.filename_hint)
    except RuntimeError as ex:
        raise HTTPException(status_code=500, detail=str(ex))
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


def _run_video_render_job(job_id: str, payload: PlaygroundVideoRenderRequest) -> None:
    try:
        update_video_job(job_id, status="processing", progress=10, message="Preparing scene plan.")
        plan = {
            "language": payload.language,
            "fps": payload.fps,
            "scenes": [scene.model_dump() for scene in payload.scenes],
        }
        update_video_job(job_id, status="processing", progress=35, message="Rendering CPU frames with FFmpeg.")
        result = render_text_plan(plan, filename_hint=payload.filename_hint)
        update_video_job(job_id, status="done", progress=100, message="CPU MP4 ready.", result=result)
    except Exception as ex:
        update_video_job(job_id, status="error", progress=0, message="CPU render failed.", error=str(ex))


@app.post("/api/playground/video/render-job")
def api_playground_video_render_job(
    payload: PlaygroundVideoRenderRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    if not payload.scenes:
        raise HTTPException(status_code=400, detail="At least one scene is required.")
    job = create_video_job(job_type="cpu_scene_render", title=payload.filename_hint)
    background_tasks.add_task(_run_video_render_job, str(job["job_id"]), payload)
    return job


@app.post("/api/playground/video/wan-render")
def api_playground_video_wan_render(
    payload: PlaygroundVideoWanRequest,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    try:
        return render_wan_text_video(
            prompt=payload.prompt,
            task=payload.task,
            size=payload.size,
            ckpt_dir=payload.ckpt_dir,
            wan_repo_dir=payload.wan_repo_dir,
            wan_python=payload.wan_python,
            offload_model=payload.offload_model,
            t5_cpu=payload.t5_cpu,
            sample_steps=payload.sample_steps,
            sample_shift=payload.sample_shift,
            sample_guide_scale=payload.sample_guide_scale,
            base_seed=payload.base_seed,
            timeout_seconds=payload.timeout_seconds,
            filename_hint=payload.filename_hint,
        )
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    except RuntimeError as ex:
        raise HTTPException(status_code=500, detail=str(ex))
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@app.post("/api/playground/video/stitch-images")
def api_playground_video_stitch_images(
    payload: PlaygroundVideoStitchRequest,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    try:
        return render_stitched_images(
            input_dir=payload.input_dir,
            seconds_per_image=payload.seconds_per_image,
            fps=payload.fps,
            width=payload.width,
            height=payload.height,
            filename_hint=payload.filename_hint,
        )
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    except RuntimeError as ex:
        raise HTTPException(status_code=500, detail=str(ex))
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


def _run_video_stitch_job(job_id: str, payload: PlaygroundVideoStitchRequest) -> None:
    try:
        update_video_job(job_id, status="processing", progress=15, message="Collecting source images.")
        update_video_job(job_id, status="processing", progress=40, message="Stitching images with local FFmpeg.")
        result = render_stitched_images(
            input_dir=payload.input_dir,
            seconds_per_image=payload.seconds_per_image,
            fps=payload.fps,
            width=payload.width,
            height=payload.height,
            filename_hint=payload.filename_hint,
        )
        update_video_job(job_id, status="done", progress=100, message="Image stitch MP4 ready.", result=result)
    except Exception as ex:
        update_video_job(job_id, status="error", progress=0, message="Image stitch failed.", error=str(ex))


@app.post("/api/playground/video/stitch-images-job")
def api_playground_video_stitch_images_job(
    payload: PlaygroundVideoStitchRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    job = create_video_job(job_type="image_stitch", title=payload.filename_hint)
    background_tasks.add_task(_run_video_stitch_job, str(job["job_id"]), payload)
    return job


@app.get("/api/playground/video/job/{job_id}")
def api_playground_video_job(
    job_id: str,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    job = get_video_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Video job not found.")
    return job


@app.get("/api/playground/video/jobs")
def api_playground_video_jobs(
    limit: int = Query(default=12, ge=1, le=100),
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    return {"ok": True, "items": list_video_jobs(limit=limit)}


@app.get("/api/playground/video/file/{file_name}")
def api_playground_video_file(
    file_name: str,
    _: None = Depends(_admin_auth_dependency),
) -> FileResponse:
    file_path = resolve_output_file(file_name)
    if file_path is None:
        raise HTTPException(status_code=404, detail="File not found.")
    media_type = "video/mp4" if file_path.suffix.lower() == ".mp4" else "text/plain; charset=utf-8"
    return FileResponse(path=file_path, filename=file_path.name, media_type=media_type)


@app.post("/api/escalation/query")
def api_escalation_query(payload: EscalationQueryRequest, request: Request) -> dict[str, Any]:
    settings = get_settings()
    queue_cfg = get_escalation_queue_settings(settings)
    if bool(queue_cfg.get("require_admin_auth_for_api", True)):
        _require_admin_auth(request)
    try:
        return submit_escalation(payload.model_dump())
    except PermissionError as ex:
        raise HTTPException(status_code=403, detail=str(ex))
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@app.get("/api/escalation/queries")
def api_escalation_queries(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    settings = get_settings()
    queue_cfg = get_escalation_queue_settings(settings)
    if bool(queue_cfg.get("require_admin_auth_for_api", True)):
        _require_admin_auth(request)
    items = list_escalations(limit=limit)
    return {"ok": True, "count": len(items), "items": items}


@app.get("/api/escalation/status")
def api_escalation_status(request: Request) -> dict[str, Any]:
    settings = get_settings()
    queue_cfg = get_escalation_queue_settings(settings)
    if bool(queue_cfg.get("require_admin_auth_for_api", True)):
        _require_admin_auth(request)

    status = get_escalation_queue_runtime_status(settings)
    queue_dir = Path(str(status.get("queue_dir") or ""))
    queue_count = 0
    if queue_dir.exists():
        queue_count = sum(1 for _ in queue_dir.glob("*_request.json"))
    return {
        "ok": True,
        "status": status,
        "queue_count": queue_count,
        "recent": list_escalations(limit=20),
    }


@app.get("/api/assessment/status")
def api_assessment_status() -> dict[str, Any]:
    state = assessment_pipeline.get_state()
    state["runtime"] = assessment_pipeline.settings_snapshot()
    return state


@app.post("/api/assessment/run")
def api_assessment_run(payload: AssessmentRunRequest) -> dict[str, Any]:
    try:
        if payload.action == "start_run":
            return assessment_pipeline.start_run(notes=payload.notes)
        if payload.action == "advance":
            return assessment_pipeline.advance(payload.stage, notes=payload.notes)
        if payload.action == "run_hle_sample":
            return assessment_pipeline.run_hle_sample(sample_size=payload.sample_size)
        if payload.action == "run_data_parsing":
            from . import ml_pipeline
            return ml_pipeline.run_data_parsing()
        if payload.action == "ml_status":
            from . import ml_pipeline
            return {
                "ok": True,
                "data_parsing": ml_pipeline.last_stage_report("data_parsing"),
                "training_phase_1": ml_pipeline.last_stage_report("training_phase_1"),
                "probe_present": (ml_pipeline.PROBE_PATH).exists(),
                "runner": "scripts/run_training_phase1.py under .venv-ml (stage 2 stays off the API server)",
            }
        if payload.action == "open_functional_gate":
            # §58 owner override — opens SWE-bench for a FUNCTIONAL CHECK only.
            return assessment_pipeline.open_functional_gate(notes=payload.notes)
        if payload.action == "swe_functional_check":
            return assessment_pipeline.swe_functional_check()
        raise ValueError(
            "Unknown action. Valid: start_run | advance | run_hle_sample | run_data_parsing | ml_status | open_functional_gate | swe_functional_check."
        )
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    except Exception as ex:
        return {"ok": False, "error": str(ex), "reason": "assessment_error"}


@app.get("/api/assessment/datasets")
def api_assessment_datasets() -> dict[str, Any]:
    return assessment_pipeline.datasets_status()


# ---------------------------------------------------------------------------
# §60 — Intake firewall: warn / quarantine / approve / delete unlabeled docs
# ---------------------------------------------------------------------------


@app.get("/api/intake/firewall")
def api_intake_firewall_status(_: None = Depends(_admin_auth_dependency)) -> dict[str, Any]:
    from . import intake_firewall

    return intake_firewall.status()


@app.post("/api/intake/firewall/scan")
def api_intake_firewall_scan(_: None = Depends(_admin_auth_dependency)) -> dict[str, Any]:
    from . import intake_firewall

    return intake_firewall.scan()


@app.post("/api/intake/firewall/approve")
def api_intake_firewall_approve(
    payload: IntakeApproveRequest,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    from . import intake_firewall

    result = intake_firewall.approve(
        payload.document_id,
        payload.scientific_field,
        domain=payload.domain,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Approve failed.")
    return result


@app.post("/api/intake/firewall/delete/{document_id}")
def api_intake_firewall_delete(
    document_id: int,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    from . import intake_firewall

    result = intake_firewall.delete(document_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Delete failed.")
    return result


# ---------------------------------------------------------------------------
# §61 — Dataset scout: candidate discovery in owner priority order
# 1) OpenAlex  2) Medical (Europe PMC)  3) GitHub  4) HuggingFace
# ---------------------------------------------------------------------------


@app.post("/api/datasets/discover")
def api_datasets_discover(
    payload: ScoutRequest,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    from . import dataset_scout

    result = dataset_scout.discover(
        payload.query,
        limit_per_source=payload.limit_per_source,
        sources=payload.sources or None,
        bypass_blocks=bool(payload.bypass_blocks),
        lens=payload.lens or None,
    )
    if not result.get("ok") and result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ---------------------------------------------------------------------------
# §64 — Owner source blocklist ("once blocked, always blocked"): sub-standard
# origins are filtered from scout discovery BEFORE the review surface, so
# review effort shrinks instead of re-judging the same noise. Unblock is an
# API-only safety valve; the UI never offers it.
# ---------------------------------------------------------------------------


@app.get("/api/datasets/blocks")
def api_datasets_blocks_list(
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    from . import dataset_scout

    return dataset_scout.list_blocks()


@app.post("/api/datasets/block")
def api_datasets_block(
    payload: ScoutBlockRequest,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    from . import dataset_scout

    result = dataset_scout.block_source(
        payload.origin,
        label=payload.label,
        source=payload.source,
        scope=payload.scope,
        note=payload.note,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.delete("/api/datasets/block/{origin}")
def api_datasets_unblock(
    origin: str,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    from . import dataset_scout

    result = dataset_scout.unblock_source(origin)
    if not result.get("ok") or not result.get("removed"):
        raise HTTPException(status_code=404, detail="no such block")
    return result


# ---------------------------------------------------------------------------
# §65 — Owner source rubric: the doctoral-level benchmark (docs/
# source_assessment_benchmark.md) applied MANUALLY per candidate source.
# The judgment stays with the owner; the module automates structure,
# scoring arithmetic, and memory only.
# ---------------------------------------------------------------------------


@app.get("/api/sources/rubric")
def api_sources_rubric() -> dict[str, Any]:
    from . import source_rubric

    return source_rubric.get_rubric()


@app.post("/api/sources/assess")
def api_sources_assess(
    payload: SourceAssessRequest,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    from . import source_rubric

    result = source_rubric.save_assessment(
        payload.origin,
        payload.scores,
        source=payload.source,
        label=payload.label,
        note=payload.note,
        nqf_level_reach=payload.nqf_level_reach,
        builds_through=payload.builds_through,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.get("/api/sources/assessments")
def api_sources_assessments(
    origins: str = "",
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    from . import source_rubric

    wanted = [o.strip() for o in origins.split(",") if o.strip()] or None
    return source_rubric.get_assessments(wanted)


@app.delete("/api/sources/assess/{origin}")
def api_sources_assess_delete(
    origin: str,
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    """§65 API-only correction valve (the UI offers re-assessment, not delete)."""
    from . import source_rubric

    result = source_rubric.delete_assessment(origin)
    if not result.get("ok") or not result.get("removed"):
        raise HTTPException(status_code=404, detail="no such assessment")
    return result


@app.get("/api/taxonomy/bloom")
def api_taxonomy_bloom() -> dict[str, Any]:
    """67: Bloom's cognitive domain as tag families (owner focus: Evaluate, Create)."""
    from . import cognitive_taxonomy

    return cognitive_taxonomy.get_taxonomy()


@app.get("/api/victus/status")
def api_victus_status() -> dict[str, Any]:
    """READ-ONLY by design: no arm, no probe, no kill over HTTP.
    The challenger stays dormant unless the operator acts in-process (§42)."""
    return {
        "ok": True,
        "status": victus_module.status(),
        "gates": victus_module.gate_report(),
        "rules": victus_module.rules_snapshot(),
        "doctrine": "Victus is permanently dormant over HTTP; fail-closed by §42 design.",
    }


@app.post("/api/ingest/files")
def api_ingest_files(payload: IngestFilesRequest) -> dict[str, Any]:
    if not payload.paths:
        raise HTTPException(status_code=400, detail="paths is required.")
    return ingest_files(payload.paths, metadata=payload.metadata)


@app.post("/api/ingest/url")
def api_ingest_url(payload: IngestUrlRequest) -> dict[str, Any]:
    try:
        return ingest_url(payload.url, metadata=payload.metadata)
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


def _safe_upload_segment(value: str | None, fallback: str = "unspecified") -> str:
    text = str(value or "").strip()
    if not text:
        text = fallback
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in text)
    safe = "-".join(part for part in safe.split("-") if part)
    return (safe or fallback)[:80]


def _task_attachment_from_upload(item: dict[str, Any], *, uploaded_at: str) -> dict[str, Any]:
    return {
        "original_name": str(item.get("original_name") or ""),
        "stored_name": str(item.get("stored_name") or ""),
        "stored_path": str(item.get("stored_path") or ""),
        "title": str(item.get("title") or ""),
        "source_id": str(item.get("source_id") or ""),
        "document_id": item.get("document_id"),
        "chunk_count": item.get("chunk_count"),
        "bytes": item.get("bytes"),
        "uploaded_at": uploaded_at,
    }


async def _store_and_ingest_uploaded_files(
    *,
    session_id: str | None,
    files: list[UploadFile],
    scientific_field: str | None = None,
) -> dict[str, Any]:
    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one document.")
    if len(files) > SENTINEL_MAX_UPLOAD_FILES:
        raise HTTPException(status_code=400, detail=f"Upload up to {SENTINEL_MAX_UPLOAD_FILES} files at a time.")

    settings = get_settings()
    raw_root = Path(settings.get("paths", {}).get("raw_root") or (get_project_root() / "data" / "raw")).resolve()
    max_bytes = SENTINEL_DOC_MAX_MB * 1024 * 1024
    pdf_max_bytes = SENTINEL_PDF_MAX_MB * 1024 * 1024
    clean_session = _safe_upload_segment(session_id, "session-transient")

    items: list[dict[str, Any]] = []
    stored_paths: list[str] = []
    for upload in files:
        original_name = str(upload.filename or "").strip() or "upload.bin"
        target = allocate_chat_upload_path(raw_root, clean_session, original_name)
        written = 0
        is_pdf = original_name.lower().endswith(".pdf")
        effective_limit = pdf_max_bytes if is_pdf else max_bytes
        effective_limit_mb = SENTINEL_PDF_MAX_MB if is_pdf else SENTINEL_DOC_MAX_MB
        try:
            with target.open("wb") as handle:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > effective_limit:
                        raise ValueError(f"{original_name} exceeds the {effective_limit_mb} MB upload limit.")
                    handle.write(chunk)
            if written <= 0:
                raise ValueError(f"{original_name} is empty.")
            stored_paths.append(str(target))
            items.append(
                {
                    "original_name": original_name,
                    "stored_name": target.name,
                    "stored_path": str(target),
                    "bytes": written,
                    "uploaded": True,
                    "ingest_ok": False,
                }
            )
        except Exception as ex:
            try:
                if target.exists():
                    target.unlink()
            except Exception:
                pass
            items.append(
                {
                    "original_name": original_name,
                    "stored_name": "",
                    "stored_path": "",
                    "bytes": written,
                    "uploaded": False,
                    "ingest_ok": False,
                    "error": str(ex),
                }
            )
        finally:
            await upload.close()

    if not stored_paths:
        first_error = next((str(item.get("error") or "") for item in items if item.get("error")), "")
        raise HTTPException(status_code=400, detail=first_error or "No uploaded documents were accepted.")

    ingest_meta: dict[str, Any] = {
        "module": "chat-upload",
        "topic": f"session-{clean_session}",
        "priority": 160,
        "publisher": "Sentinari Operator Upload",
        "license": "operator-provided",
    }
    if scientific_field and str(scientific_field).strip():
        ingest_meta["scientific_field"] = str(scientific_field).strip()

    ingest_summary = ingest_files(stored_paths, metadata=ingest_meta, allow_embeddings=True)
    by_path = {str(item.get("stored_path") or ""): item for item in items if item.get("stored_path")}
    for res_item in ingest_summary.get("items") or []:
        p_str = str(res_item.get("path") or "")
        entry = by_path.get(p_str)
        if entry is None:
            continue
        if res_item.get("ok"):
            entry.update(
                {
                    "ingest_ok": True,
                    "document_id": res_item.get("document_id"),
                    "source_id": res_item.get("source_id"),
                    "title": res_item.get("title") or entry.get("original_name"),
                    "chunk_count": res_item.get("chunk_count") or 0,
                    "pdf_engine": res_item.get("pdf_engine") or "",
                }
            )
        else:
            entry["error"] = str(res_item.get("error") or "Ingestion failed.")

    ingested = int(ingest_summary.get("ingested") or 0)
    failed = int(ingest_summary.get("failed") or 0)
    if ingested <= 0:
        first_error = next((str(item.get("error") or "") for item in items if item.get("error")), "")
        raise HTTPException(status_code=400, detail=first_error or "Uploaded files could not be indexed.")

    return {
        "ok": True,
        "session_id": clean_session,
        "uploaded": len(stored_paths),
        "ingested": ingested,
        "failed": failed,
        "items": items,
    }


@app.post("/api/chat/upload")
async def api_chat_upload(
    session_id: str | None = Query(default=None, max_length=120),
    files: list[UploadFile] = File(...),
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    return await _store_and_ingest_uploaded_files(session_id=session_id, files=files)


@app.post("/api/admin/tasks/{task_id}/upload")
async def api_admin_task_upload(
    task_id: int,
    files: list[UploadFile] = File(...),
    _: None = Depends(_admin_auth_dependency),
) -> dict[str, Any]:
    with get_connection() as conn:
        task = get_task(conn, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")

    result = await _store_and_ingest_uploaded_files(session_id=f"task-{task_id}", files=files)
    uploaded_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    task_attachments = [
        _task_attachment_from_upload(item, uploaded_at=uploaded_at)
        for item in result.get("items") or []
        if bool(item.get("ingest_ok"))
    ]
    with get_connection() as conn:
        updated_task = update_task_attachments(conn, task_id=task_id, attachments=task_attachments)
        if updated_task is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        conn.commit()

    result["task"] = updated_task
    return result


@app.post("/api/unsupervised/rebuild")
def api_unsupervised_rebuild(payload: UnsupervisedRebuildRequest) -> dict[str, Any]:
    with get_connection() as conn:
        result = rebuild_unsupervised_clusters(
            conn,
            requested_clusters=payload.requested_clusters,
            scientific_field=payload.scientific_field,
            vocational_discipline=payload.vocational_discipline,
            source_collection=payload.source_collection,
            min_chunks=payload.min_chunks,
            max_terms_per_cluster=payload.max_terms_per_cluster,
            force_lexical=payload.force_lexical,
        )
        conn.commit()
    return result


@app.get("/api/unsupervised/runs")
def api_unsupervised_runs(limit: int = Query(default=30, ge=1, le=500)) -> dict[str, Any]:
    with get_connection() as conn:
        rows = list_unsupervised_runs(conn, limit=limit)
    return {"ok": True, "count": len(rows), "items": rows}


@app.get("/api/unsupervised/clusters")
def api_unsupervised_clusters(
    run_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=250, ge=1, le=1000),
) -> dict[str, Any]:
    with get_connection() as conn:
        rows = list_unsupervised_clusters(conn, run_id=run_id, limit=limit)
    return {"ok": True, "count": len(rows), "items": rows}


@app.get("/api/unsupervised/clusters/{cluster_id}/members")
def api_unsupervised_cluster_members(
    cluster_id: int,
    limit: int = Query(default=120, ge=1, le=1000),
) -> dict[str, Any]:
    with get_connection() as conn:
        rows = list_cluster_members(conn, cluster_id=cluster_id, limit=limit)
    return {"ok": True, "count": len(rows), "items": rows}


@app.post("/api/search")
def api_search(payload: SearchRequest) -> dict[str, Any]:
    with get_connection() as conn:
        results = search_chunks(
            conn,
            query=payload.query,
            limit=max(1, min(50, payload.limit)),
            module=payload.module,
            topic=payload.topic,
            scientific_field=payload.scientific_field,
            vocational_discipline=payload.vocational_discipline,
            source_collection=payload.source_collection,
        )
    return {"ok": True, "count": len(results), "results": results}


@app.post("/api/chat")
def api_chat(payload: ChatRequest) -> dict[str, Any]:
    settings = get_settings()
    result = run_chat(
        message=payload.message,
        mode=payload.mode,
        session_id=payload.session_id,
        top_k=clamp_top_k(payload.top_k, settings=settings),
        behavior_variant=payload.behavior_variant,
        qualia_control=payload.qualia_control,
        use_web_fetch=payload.use_web_fetch,
        module=payload.module,
        topic=payload.topic,
        scientific_field=payload.scientific_field,
        vocational_discipline=payload.vocational_discipline,
        source_collection=payload.source_collection,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Chat failed.")
    return result


@app.get("/api/chat/history")
def api_chat_history(
    session_id: str = Query(..., min_length=1, max_length=120),
    limit: int = Query(default=60, ge=1, le=200),
) -> dict[str, Any]:
    settings = get_settings()
    try:
        with get_read_connection() as conn:
            return {"ok": True, **get_session_history_readonly(conn, session_id, limit=limit, settings=settings)}
    except sqlite3.OperationalError as ex:
        if "locked" not in str(ex).lower():
            raise
        return {
            "ok": True,
            "busy": True,
            "session_id": session_id,
            "count": 0,
            "summary": "",
            "summary_updated_at": "",
            "items": [],
            "detail": "Chat history is busy. The page will retry shortly.",
        }


@app.get("/api/taxonomy/list")
def api_taxonomy_list() -> dict[str, Any]:
    with get_connection() as conn:
        rows = list_taxonomy(conn)
    return {"ok": True, "count": len(rows), "items": rows}


@app.post("/api/taxonomy/configure")
def api_taxonomy_configure(payload: TaxonomyConfigureRequest) -> dict[str, Any]:
    with get_connection() as conn:
        result = configure_taxonomy(
            conn,
            scientific_fields=payload.scientific_fields,
            vocational_disciplines=payload.vocational_disciplines,
            curricula=payload.curricula,
        )
        conn.commit()
    return result


@app.post("/api/taxonomy/scan-now")
def api_taxonomy_scan_now() -> dict[str, Any]:
    result = _auto_ingest_service.scan_once()
    return {"ok": True, **result}


@app.get("/api/ingest/state")
def api_ingest_state(limit: int = Query(default=200, ge=1, le=2000)) -> dict[str, Any]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT path, file_size, mtime_utc, checksum, last_status, last_error, updated_at
            FROM file_ingest_state
            ORDER BY updated_at DESC
            LIMIT ?;
            """,
            (int(limit),),
        ).fetchall()
    return {"ok": True, "count": len(rows), "items": [dict(r) for r in rows]}


@app.get("/api/diagnostics/architecture")
def api_diagnostics_architecture(_: None = Depends(_admin_auth_dependency)) -> dict[str, Any]:
    settings = get_settings()
    checks: list[dict[str, Any]] = []

    def add_check(name: str, ok: bool, detail: str, data: dict[str, Any] | None = None) -> None:
        checks.append(
            {
                "name": name,
                "ok": bool(ok),
                "detail": detail,
                "data": data or {},
            }
        )

    add_check(
        "config_path",
        bool(get_config_path().exists()),
        f"Config path: {get_config_path()}",
    )

    try:
        with get_connection() as conn:
            conn.execute("SELECT 1;").fetchone()
        add_check("sqlite_connectivity", True, "SQLite connection and query succeeded.")
    except Exception as ex:
        add_check("sqlite_connectivity", False, f"SQLite query failed: {ex}")

    auth = get_admin_auth_settings(settings)
    auth_ok = (not auth["enabled"]) or auth["configured"]
    if auth["enabled"] and not auth["configured"]:
        auth_detail = (
            f"Enabled but not configured. Set {auth['password_env']} or SENTINARI_ADMIN_PASSWORD before using admin routes."
        )
    elif auth["enabled"]:
        auth_detail = f"Enabled and configured for user '{auth['username']}'."
    else:
        auth_detail = "Disabled by configuration."
    add_check(
        "admin_single_login",
        auth_ok,
        auth_detail,
        data={
            "enabled": bool(auth["enabled"]),
            "configured": bool(auth["configured"]),
            "username": str(auth["username"]),
            "session_ttl_hours": int(auth["session_ttl_hours"]),
        },
    )

    policy = evaluate_runtime_llm_policy(settings)
    add_check(
        "llm_firewall_policy",
        bool(policy.get("ok")),
        "LLM firewall validation passed." if policy.get("ok") else "; ".join(policy.get("violations") or []),
        data={
            "provider": policy.get("provider"),
            "chat_model": policy.get("chat_model"),
            "embedding_model": policy.get("embedding_model"),
            "firewall": policy.get("firewall"),
        },
    )

    llm = settings.get("llm", {}) if isinstance(settings.get("llm"), dict) else {}
    parsed_temperature = clamp_temperature(llm.get("temperature"), settings=settings)
    # Cord-cut aware: build_ollama_client() returns the gateway-backed client
    # when runtime_llm.client_backend = gateway, else the legacy Ollama client.
    client = build_ollama_client()
    if is_ollama_runtime_probe_disabled():
        llm_runtime = _apply_ollama_boundary_status(
            build_ollama_boundary_runtime(client.base_url, client.chat_model, client.embedding_model)
        )
        ollama_ok = False
    else:
        llm_runtime = _apply_ollama_boundary_status(client.get_runtime_diagnostics())
        ollama_ok = client.is_available()
    models = client.list_models() if ollama_ok else []
    ollama_boundary_disabled = _is_ollama_autostart_disabled()
    add_check(
        "ollama_connectivity",
        ollama_ok or ollama_boundary_disabled,
        (
            "Ollama API reachable."
            if ollama_ok
            else "Ollama autostart is intentionally disabled by local boundary control."
        ),
        data={"base_url": str(llm.get("base_url") or ""), "models": models},
    )

    if models:
        configured_chat = str(llm.get("chat_model") or "").strip().lower()
        configured_embed = str(llm.get("embedding_model") or "").strip().lower()
        model_keys = {m.lower() for m in models}

        def model_exists(configured_name: str) -> bool:
            if not configured_name:
                return False
            if configured_name in model_keys:
                return True
            # Ollama may return fully tagged model names such as "nomic-embed-text:latest".
            prefix = configured_name + ":"
            return any(item.startswith(prefix) for item in model_keys)

        models_ok = model_exists(configured_chat) and model_exists(configured_embed)
        add_check(
            "ollama_models_available",
            models_ok,
            (
                f"Configured models found (chat={configured_chat}, embedding={configured_embed})."
                if models_ok
                else f"Configured models missing (chat={configured_chat}, embedding={configured_embed})."
            ),
        )
    else:
        add_check(
            "ollama_models_available",
            not ollama_ok,
            (
                "Skipped model availability check because Ollama autostart is disabled."
                if ollama_boundary_disabled
                else "Skipped model availability check because Ollama is unreachable."
            ),
        )

    transport_ok = bool(llm_runtime.get("ready")) or ollama_boundary_disabled
    transport_detail = str(llm_runtime.get("operator_trigger") or "LLM runtime is ready for normal chat.")
    add_check(
        "ollama_chat_transport",
        transport_ok,
        transport_detail,
        data=llm_runtime,
    )

    add_check(
        "auto_ingest_service",
        _auto_ingest_service.is_running(),
        (
            f"Auto-ingest running with {int(_auto_ingest_service.poll_seconds)} second polling."
            if _auto_ingest_service.is_running()
            else "Auto-ingest is currently stopped."
        ),
    )

    route_paths = {route.path for route in app.routes}

    logic_probe_ok = False
    logic_probe_detail = ""
    try:
        probe = run_chat(
            message="SMi diagnostic logic probe",
            mode="knowledge",
            top_k=1,
            use_web_fetch=False,
            session_id=f"diag-{int(datetime.now(tz=timezone.utc).timestamp())}",
        )
        logic_probe_ok = bool(probe.get("ok")) and bool(str(probe.get("answer") or "").strip())
        logic_probe_detail = (
            "Chat pipeline returned a valid answer."
            if logic_probe_ok
            else "Chat pipeline returned no answer."
        )
    except Exception as ex:
        logic_probe_ok = False
        logic_probe_detail = f"Chat logic probe failed: {ex}"
    add_check("chat_logic_probe", logic_probe_ok, logic_probe_detail)

    passed = sum(1 for item in checks if item["ok"])
    failed = len(checks) - passed
    overall_ok = failed == 0
    return {
        "ok": overall_ok,
        "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
        "summary": {"total": len(checks), "passed": passed, "failed": failed},
        "warnings": llm_runtime.get("warnings") or [],
        "checks": checks,
    }


@app.get("/api/tools/shell/policy")
def api_tools_shell_policy(request: Request) -> dict[str, Any]:
    settings = get_settings()
    runtime = settings.get("runtime", {})
    policy = get_shell_policy(settings, get_project_root())

    if bool(policy.get("require_admin_auth", True)):
        auth = get_admin_auth_settings(settings)
        if not auth["enabled"]:
            raise HTTPException(
                status_code=403,
                detail="Shell policy requires admin_auth.enabled=true before shell routes can be used.",
            )
        _require_admin_auth(request)

    return {
        "ok": True,
        "allow_shell_tools": bool(runtime.get("allow_shell_tools", False)),
        "policy": get_public_shell_policy(policy),
    }


@app.post("/api/tools/shell/workflow/reset")
def api_tools_shell_workflow_reset(
    request: Request,
    session_id: str = Query(..., min_length=1, max_length=120),
) -> dict[str, Any]:
    settings = get_settings()
    policy = get_shell_policy(settings, get_project_root())
    if bool(policy.get("require_admin_auth", True)):
        auth = get_admin_auth_settings(settings)
        if not auth["enabled"]:
            raise HTTPException(
                status_code=403,
                detail="Shell policy requires admin_auth.enabled=true before shell routes can be used.",
            )
        _require_admin_auth(request)

    reset = reset_workflow_state(session_id=session_id)
    append_shell_audit_event(
        policy,
        {
            "event": "shell_workflow_reset",
            "session_id": session_id,
            "reset": bool(reset),
            "client_ip": request.client.host if request.client else "",
        },
    )
    return {"ok": True, "session_id": session_id, "reset": bool(reset)}


@app.post("/api/tools/shell")
def api_tools_shell(payload: ShellRunRequest, request: Request) -> dict[str, Any]:
    settings = get_settings()
    runtime = settings.get("runtime", {})
    if not bool(runtime.get("allow_shell_tools", False)):
        raise HTTPException(
            status_code=403,
            detail="Shell tools are disabled. Enable runtime.allow_shell_tools=true in config/settings.yaml.",
        )

    policy = get_shell_policy(settings, get_project_root())
    if bool(policy.get("require_admin_auth", True)):
        auth = get_admin_auth_settings(settings)
        if not auth["enabled"]:
            raise HTTPException(
                status_code=403,
                detail="Shell policy requires admin_auth.enabled=true before shell routes can be used.",
            )
        _require_admin_auth(request)

    command = (payload.command or "").strip()
    decision = evaluate_shell_request(
        command=command,
        policy=policy,
        project_root=get_project_root(),
        session_id=payload.session_id,
        workflow_step=payload.workflow_step,
        approval_token=payload.approval_token,
        dry_run=bool(payload.dry_run),
    )

    append_shell_audit_event(
        policy,
        {
            "event": "shell_request",
            "command": command,
            "session_id": payload.session_id or "",
            "workflow_step": payload.workflow_step or "",
            "dry_run": bool(payload.dry_run),
            "allowed": bool(decision.get("allowed", False)),
            "execute": bool(decision.get("execute", False)),
            "operation": str(decision.get("operation") or ""),
            "policy_mode": str(decision.get("policy_mode") or ""),
            "reason": str(decision.get("reason") or ""),
            "client_ip": request.client.host if request.client else "",
        },
    )

    if not bool(decision.get("allowed", False)):
        raise HTTPException(
            status_code=int(decision.get("status_code") or 403),
            detail=str(decision.get("reason") or "Command blocked by shell policy."),
        )

    if not bool(decision.get("execute", False)):
        return {
            "ok": True,
            "executed": False,
            "reason": str(decision.get("reason") or "Command execution skipped."),
            "operation": decision.get("operation"),
            "policy_mode": decision.get("policy_mode"),
            "paths": decision.get("paths") or [],
            "workflow": decision.get("workflow") or {},
        }

    timeout = max(
        1,
        min(
            int(payload.timeout_seconds or 30),
            int(policy.get("max_timeout_seconds") or 90),
        ),
    )

    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as ex:
        append_shell_audit_event(
            policy,
            {
                "event": "shell_execution_timeout",
                "command": command,
                "session_id": payload.session_id or "",
                "workflow_step": payload.workflow_step or "",
                "timeout_seconds": timeout,
                "client_ip": request.client.host if request.client else "",
            },
        )
        return {
            "ok": False,
            "executed": True,
            "timed_out": True,
            "exit_code": None,
            "timeout_seconds": timeout,
            "stdout": ex.stdout or "",
            "stderr": ex.stderr or "",
            "operation": decision.get("operation"),
            "policy_mode": decision.get("policy_mode"),
        }

    append_shell_audit_event(
        policy,
        {
            "event": "shell_execution_result",
            "command": command,
            "session_id": payload.session_id or "",
            "workflow_step": payload.workflow_step or "",
            "exit_code": completed.returncode,
            "ok": completed.returncode == 0,
            "timeout_seconds": timeout,
            "client_ip": request.client.host if request.client else "",
        },
    )

    return {
        "ok": completed.returncode == 0,
        "executed": True,
        "timed_out": False,
        "exit_code": completed.returncode,
        "timeout_seconds": timeout,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "operation": decision.get("operation"),
        "policy_mode": decision.get("policy_mode"),
        "workflow": decision.get("workflow") or {},
    }
