"""Sentinel Learning Index — proof that ingested knowledge is *applied*, not just held.

Owner directive (§36): a background worker that determines, per ingested
document, whether Sentinel can actually apply the knowledge, and reports a
% Learned progress per scientific field and for the whole library.

Honest method — every assessment is one evidence-graded exam:
1. EXAM     — pull a few chunks of one not-yet-assessed document and ask the
              LLM gateway to write ONE exam question grounded ONLY in that
              text, then answer it from the model's own knowledge WITHOUT
              quoting the passage back.
2. GRADE    — grading is local (no extra API cost): the answer is scored
              against the source text by token-overlap GROUNDING (did she use
              the knowledge?), with a VERBATIM penalty so reciting the
              passage is not mistaken for mastery.
3. RECORD   — the graded result is persisted per document; the index
              aggregates to per-field and whole-library percentages.

Nothing here mutates knowledge: this is measurement, not modification —
the Qualia Lab's verification discipline, run continuously and gently.
Verdict thresholds are deliberately conservative and should be calibrated
against Qualia Lab results as data accumulates.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .db import get_connection, library_connection
from .llm_gateway import LLMGatewayError, get_gateway

router = APIRouter(prefix="/api/learning", tags=["learning"])

# Gentle-by-design pacing: one document per tick, tick every 10s (~6 exams/min).
# §58 engine-off guard: when the LLM gateway is dark, the worker must IDLE —
# the old failure path marked documents 'skipped' (consuming them without
# exams). A skipped document is only legitimate when the exam itself ran and
# the material was unloadable — never when the engine is simply offline.
POLL_INTERVAL_SECONDS = 0.5
CHUNKS_PROBED = 3
MAX_CHARS_PER_CHUNK = 3500
MAX_CHARS_SOURCE = 9000
LLM_TEMPERATURE = 0.2
LLM_MAX_TOKENS = 2048
# Documents are scanned newest-first; this window keeps each tick cheap while
# the index sweeps the whole library over time.
RECENT_WINDOW = 400

# 74b: a LIT but useless engine must never burn documents. After this many
# consecutive engine failures (error or unusable output) the worker ends the
# cycle and waits for the next tick - documents stay pending, retries are
# free, and the counter below surfaces the state in /api/learning/status.
MAX_CONSECUTIVE_ENGINE_FAILURES = 5
_engine_failure_state = {
    "consecutive": 0,
    "total": 0,
    "last_reason": "",
    "last_document_id": None,
}


def _note_engine_failure(reason: str, document_id: int | None = None) -> None:
    _engine_failure_state["consecutive"] += 1
    _engine_failure_state["total"] += 1
    _engine_failure_state["last_reason"] = reason
    _engine_failure_state["last_document_id"] = document_id


def _clear_engine_failure() -> None:
    _engine_failure_state["consecutive"] = 0
    _engine_failure_state["last_reason"] = ""
    _engine_failure_state["last_document_id"] = None

# §58 — Owner-set learning priority (1 = examined first, rest follow in any
# order). Exact-name first, then prefix match, so 'computer-and-information-'
# hits 'computer-and-information-sciences'. Applied in _candidate_documents.
LEARNING_PRIORITY_FIELDS: tuple[str, ...] = (
    "computer-and-information-sciences",  # 1) AI and Information Science
    "information-science",
    "artificial-intelligence",
    "physics",                             # 2) Physics
    "engineering",                         # 3) Engineering
)

EXAM_SYSTEM_PROMPT = """You are Sentinel. You are being examined on knowledge you have ingested. \
Write ONE exam question grounded ONLY in the provided text, then answer it from your own understanding. \
Answer in your own words — do NOT copy phrases from the text. \
Return STRICT JSON only: {"question": "...", "answer": "..."}"""

EXAM_USER_TEMPLATE = """Text (document: "{title}", field: {field}):

{source}

Produce the JSON exam now."""


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _ensure_schema() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS learning_assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                scientific_field TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                question TEXT NOT NULL DEFAULT '',
                answer TEXT NOT NULL DEFAULT '',
                grounding_score REAL NOT NULL DEFAULT 0,
                verbatim_score REAL NOT NULL DEFAULT 0,
                mastery REAL NOT NULL DEFAULT 0,
                verdict TEXT NOT NULL DEFAULT '',
                assessed_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_learning_field
                ON learning_assessments(scientific_field);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_learning_doc
                ON learning_assessments(document_id);
            CREATE TABLE IF NOT EXISTS learning_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        conn.commit()


def _db_write_retry(fn, *args, **kwargs):
    """Tiny-write armor: the learning subsystem shares its DB with the load
    queue, auto-ingest, and the pattern store. Its writes are one-row upserts,
    so a short retry-with-backoff rides out transient 'database is locked'
    storms instead of dropping an exam result (§37 lesson)."""
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            return fn(*args, **kwargs)
        except sqlite3.OperationalError as exc:
            last_exc = exc
            time.sleep(1.5 * (attempt + 1))
    raise last_exc if last_exc else RuntimeError("db write failed")


def _get_setting(key: str, default: str) -> str:
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM learning_settings WHERE key = ?", (key,)
            ).fetchone()
        return str(row["value"]) if row is not None else default
    except Exception:
        return default


def _set_setting(key: str, value: str) -> None:
    def _write() -> None:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO learning_settings (key, value, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value),
            )
            conn.commit()

    _db_write_retry(_write)


def learning_enabled() -> bool:
    """Owner directive: Learning is active and accelerated on the local RTX 5070 Ti."""
    return _get_setting("learning_enabled", "on").lower() == "on"


def calibration_enabled() -> bool:
    """Calibration runs only when the owner explicitly enables it (§38):
    default OFF until toggled on. Persisted in learning_settings."""
    return _get_setting("calibration_enabled", "off").lower() == "on"


# ---------------------------------------------------------------------------
# Local grading — grounding with a verbatim penalty
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset(
    """the and for are but not you all any can had her was one our out day get has
    him his how man new now old see two way who boy did its let put say she too
    use that this with from they have will been were when what your said each
    which their there these those about into over under between because while
    where after before above below both few more most other some such only own
    same than them then once here does done doing having""".split()
)


def _tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]{3,}", str(text or "").lower())
    return {t for t in tokens if t not in _STOPWORDS}


def _grade_thresholds() -> tuple[float, float, float]:
    """(applied, partial_floor, recited_verbatim) — tunable via learning_settings
    so calibration (§37) can adjust verdicts without code edits."""
    try:
        applied = float(_get_setting("applied_threshold", "0.28"))
        partial = float(_get_setting("partial_threshold", "0.08"))
        recited = float(_get_setting("recited_verbatim", "0.6"))
    except Exception:
        return 0.28, 0.08, 0.6
    return (
        min(0.95, max(0.05, applied)),
        min(0.5, max(0.01, partial)),
        min(0.95, max(0.3, recited)),
    )


def _grade(answer: str, source_text: str) -> tuple[float, float, float, str]:
    """Return (grounding, verbatim, mastery, verdict).

    grounding = share of the answer's tokens that appear in the source text
                (did the answer actually draw on the material?).
    verbatim  = share of the source text's tokens parroted back (recitation).
    mastery   = grounding, penalized when the answer is mostly copied text —
                reciting a passage is not the same as applying it.
    """
    applied_t, partial_t, recited_t = _grade_thresholds()
    a_tokens = _tokenize(answer)
    s_tokens = _tokenize(source_text)
    if not a_tokens:
        return 0.0, 0.0, 0.0, "no-answer"
    grounding = len(a_tokens & s_tokens) / len(a_tokens)
    verbatim = (len(a_tokens & s_tokens) / len(s_tokens)) if s_tokens else 0.0
    if verbatim > recited_t:
        mastery = grounding * max(0.3, 1.0 - (verbatim - recited_t))
    else:
        mastery = grounding
    if mastery >= applied_t:
        verdict = "applied"
    elif verbatim > recited_t:
        verdict = "recited"
    elif grounding > partial_t:
        verdict = "partial"
    else:
        verdict = "not-learned"
    return round(grounding, 4), round(verbatim, 4), round(mastery, 4), verdict


# ---------------------------------------------------------------------------
# The exam itself
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict[str, Any] | None:
    t = re.sub(r"^```(?:json)?|```\s*$", "", str(text or "").strip(), flags=re.M).strip()
    start = t.find("{")
    end = t.rfind("}")
    if start < 0 or end <= start:
        return None
    candidate = t[start : end + 1]

    # 1. Direct standard parse
    try:
        data = json.loads(candidate, strict=False)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # 2. Repair unescaped LaTeX backslashes (\mathbb, \alpha, \sum, \frac, etc.)
    try:
        fixed = re.sub(r'\\(?![/\"\\bfnrt]|u[0-9a-fA-F]{4})', r'\\\\', candidate)
        data = json.loads(fixed, strict=False)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # 3. Fallback regex extraction of question & answer
    q_match = re.search(r'"question"\s*:\s*"((?:\\.|[^"\\])*)"', candidate, re.DOTALL)
    a_match = re.search(r'"answer"\s*:\s*"((?:\\.|[^"\\])*)"', candidate, re.DOTALL)
    if q_match and a_match:
        try:
            q_val = q_match.group(1).encode("utf-8").decode("unicode_escape", errors="replace")
            a_val = a_match.group(1).encode("utf-8").decode("unicode_escape", errors="replace")
            return {"question": q_val, "answer": a_val}
        except Exception:
            return {"question": q_match.group(1), "answer": a_match.group(1)}

    return None


def _load_probe_material(document_id: int) -> tuple[str, str, str] | None:
    """(title, scientific_field, source_text) from the knowledge library."""
    with library_connection("gemma") as conn:
        doc = conn.execute(
            "SELECT title, COALESCE(scientific_field, '') AS field FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()
        if doc is None:
            return None
        rows = conn.execute(
            "SELECT content FROM chunks WHERE document_id = ? ORDER BY chunk_index LIMIT ?",
            (document_id, CHUNKS_PROBED),
        ).fetchall()
    source = "\n\n".join(
        str(r["content"] or "")[:MAX_CHARS_PER_CHUNK] for r in rows
    ).strip()[:MAX_CHARS_SOURCE]
    if not source:
        return None
    return str(doc["title"] or "Untitled"), str(doc["field"] or "unclassified"), source


def probe_document(document_id: int) -> dict[str, Any] | None:
    """Run one exam against a specific document. None = could not assess."""
    record, _reason = _probe_document_with_reason(document_id)
    return record


def _probe_document_with_reason(document_id: int) -> tuple[dict[str, Any] | None, str]:
    """One exam attempt plus a failure REASON for the caller.

    Reasons (74b): 'no-material' = the document itself is unloadable (the
    one legitimate skip); 'engine-error' / 'engine-output-unusable' = the
    ENGINE failed, never the document — the caller must NOT consume it.
    """
    material = _load_probe_material(document_id)
    if material is None:
        return None, "no-material"
    title, field, source = material
    try:
        raw = get_gateway().chat(
            [
                {"role": "system", "content": EXAM_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": EXAM_USER_TEMPLATE.format(
                        title=title, field=field or "general", source=source
                    ),
                },
            ],
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
        )
    except (LLMGatewayError, Exception):
        _note_engine_failure("engine-error")
        return None, "engine-error"
    exam = _extract_json(raw)
    if not exam:
        _note_engine_failure("engine-output-unusable")
        return None, "engine-output-unusable"
    question = str(exam.get("question") or "")[:1000]
    answer = str(exam.get("answer") or "")[:4000]
    if not question or not answer:
        _note_engine_failure("engine-output-unusable")
        return None, "engine-output-unusable"
    grounding, verbatim, mastery, verdict = _grade(answer, source)
    record: dict[str, Any] = {
        "document_id": document_id,
        "scientific_field": _norm_field(field),
        "title": title,
        "question": question,
        "answer": answer,
        "grounding_score": grounding,
        "verbatim_score": verbatim,
        "mastery": mastery,
        "verdict": verdict,
        "assessed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _persist(record)
    _clear_engine_failure()
    safe_title = str(title or "")[:35].encode("ascii", errors="replace").decode("ascii")
    print(
        f"[learning-rtx] Doc {document_id} [{_norm_field(field)}]: '{safe_title}' -> {verdict} (mastery {mastery:.2f})",
        flush=True,
    )
    return record, "assessed"


def _persist(record: dict[str, Any]) -> None:
    _ensure_schema()

    def _write() -> None:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO learning_assessments
                    (document_id, scientific_field, title, question, answer,
                     grounding_score, verbatim_score, mastery, verdict, assessed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    scientific_field = excluded.scientific_field,
                    title = excluded.title,
                    question = excluded.question,
                    answer = excluded.answer,
                    grounding_score = excluded.grounding_score,
                    verbatim_score = excluded.verbatim_score,
                    mastery = excluded.mastery,
                    verdict = excluded.verdict,
                    assessed_at = excluded.assessed_at
                """,
                (
                    int(record["document_id"]),
                    record["scientific_field"],
                    record["title"],
                    record["question"],
                    record["answer"],
                    float(record["grounding_score"]),
                    float(record["verbatim_score"]),
                    float(record["mastery"]),
                    record["verdict"],
                    record["assessed_at"],
                ),
            )
            conn.commit()

    _db_write_retry(_write)


def _is_held_out(scientific_field: str) -> bool:
    """§59 owner rule: documents without a scientific field are NOT learning
    material. The owner manually approves datasets and by default does not
    approve untitled/unclassified ones. They stay searchable in the library,
    but are never examined and never counted toward % learned."""
    return _norm_field(scientific_field) == "unclassified"


def _priority_rank(scientific_field: str) -> int:
    """0 = highest priority (examined first); large = unprioritised rest."""
    key = _norm_field(scientific_field)
    for i, p in enumerate(LEARNING_PRIORITY_FIELDS):
        if key == _norm_field(p):
            return i
    for i, p in enumerate(LEARNING_PRIORITY_FIELDS):
        if key.startswith(_norm_field(p)):
            return i
    return len(LEARNING_PRIORITY_FIELDS)


def _candidate_documents() -> list[int]:
    """Unassessed library documents, newest first — but ordered by the
    owner's learning priority first (§58): priority-1 fields are examined
    before priority-2, before priority-3, before everything else.
    The recent window is checked first (cheap); when it is exhausted, the
    sweep continues into the rest of the library — the 10s exam pacing is
    the real throttle."""
    with library_connection("gemma") as conn:
        rows = conn.execute(
            "SELECT id, COALESCE(NULLIF(TRIM(scientific_field), ''), 'unclassified') AS f"
            " FROM documents ORDER BY id DESC LIMIT ?", (RECENT_WINDOW,)
        ).fetchall()
    entries = [(int(r["id"]), str(r["f"])) for r in rows]
    entries = [(doc_id, f) for doc_id, f in entries if not _is_held_out(f)]
    if not entries:
        return []
    library_ids = [doc_id for doc_id, _ in entries]
    placeholders = ",".join("?" for _ in library_ids)
    with get_connection() as conn:
        assessed = {
            int(r["document_id"])
            for r in conn.execute(
                f"SELECT document_id FROM learning_assessments WHERE document_id IN ({placeholders})",
                library_ids,
            ).fetchall()
        }
    pending = [(doc_id, field) for doc_id, field in entries if doc_id not in assessed]
    if pending:
        pending.sort(key=lambda item: (_priority_rank(item[1]), -item[0]))
        return [doc_id for doc_id, _ in pending]
    # Recent window fully assessed — continue the sweep deeper, priority
    # first, newest first within each band, so the whole library is
    # eventually examined (gently, one per tick).
    with library_connection("gemma") as conn:
        all_rows = conn.execute(
            "SELECT id, COALESCE(NULLIF(TRIM(scientific_field), ''), 'unclassified') AS f"
            " FROM documents ORDER BY id DESC"
        ).fetchall()
    all_entries = [(int(r["id"]), str(r["f"])) for r in all_rows]
    all_entries = [(doc_id, f) for doc_id, f in all_entries if not _is_held_out(f)]
    if not all_entries:
        return []
    all_ids = [doc_id for doc_id, _ in all_entries]
    placeholders = ",".join("?" for _ in all_ids)
    with get_connection() as conn:
        assessed_all = {
            int(r["document_id"])
            for r in conn.execute(
                f"SELECT document_id FROM learning_assessments WHERE document_id IN ({placeholders})",
                all_ids,
            ).fetchall()
        }
    pending_all = [(doc_id, field) for doc_id, field in all_entries if doc_id not in assessed_all]
    pending_all.sort(key=lambda item: (_priority_rank(item[1]), -item[0]))
    return [doc_id for doc_id, _ in pending_all]


def probe_next() -> dict[str, Any] | None:
    """Assess the next unassessed recent document. None = nothing pending / failed.

    74b — the owner's rule, made mechanical: a document is consumed as
    'skipped' ONLY when its material is unloadable (verified §58 case).
    An engine that ERRORS or returns unusable output never consumes a
    document: the failure is counted, the cycle stops after
    MAX_CONSECUTIVE_ENGINE_FAILURES attempts, and the same documents are
    offered again next tick — nothing is burned while she cannot learn.
    """
    consecutive_failures = 0
    for _ in range(8):  # small ceiling; engine failures abort the cycle early
        candidates = _candidate_documents()
        if not candidates:
            return None
        document_id = candidates[0]
        record, reason = _probe_document_with_reason(document_id)
        if record is not None:
            return record
        if reason == "no-material":
            def _mark_skipped(doc_id: int = document_id) -> None:
                with get_connection() as conn:
                    conn.execute(
                        "INSERT OR IGNORE INTO learning_assessments (document_id, verdict, assessed_at)"
                        " VALUES (?, 'skipped', ?)",
                        (doc_id, datetime.now(timezone.utc).isoformat(timespec="seconds")),
                    )
                    conn.commit()

            _db_write_retry(_mark_skipped)
            continue
        # engine-error / engine-output-unusable: consume NOTHING.
        consecutive_failures += 1
        print(
            f"[learning] engine unusable ({reason}) on document {document_id} - "
            "document NOT consumed, will retry next tick",
            flush=True,
        )
        if consecutive_failures >= MAX_CONSECUTIVE_ENGINE_FAILURES:
            print(
                f"[learning] {MAX_CONSECUTIVE_ENGINE_FAILURES} consecutive engine failures - "
                "ending this cycle; nothing consumed",
                flush=True,
            )
            return None
    return None


# ---------------------------------------------------------------------------
# The index — per-field and whole-library % learned
# ---------------------------------------------------------------------------

def _norm_field(raw: Any) -> str:
    """Merge legacy Title-case field labels ('Chemistry', 'Physics') into the
    canonical slug form so per-field percentages are not split by casing."""
    value = str(raw or "").strip().lower().replace(" ", "-")
    return value or "unclassified"


def _field_totals() -> dict[str, int]:
    try:
        with library_connection("gemma") as conn:
            rows = conn.execute(
                "SELECT COALESCE(NULLIF(TRIM(scientific_field), ''), 'unclassified') AS f, COUNT(1) AS n"
                " FROM documents GROUP BY f"
            ).fetchall()
        totals: dict[str, int] = {}
        for r in rows:
            key = _norm_field(r["f"])
            if key == "unclassified":
                continue  # §59 held out from learning accounting
            totals[key] = totals.get(key, 0) + int(r["n"])
        return totals
    except Exception:
        return {}


def learning_status() -> dict[str, Any]:
    _ensure_schema()
    totals = _field_totals()
    try:
        _gw = get_gateway().describe()
        engine = {
            "available": bool(_gw.get("available")),
            "provider": str(_gw.get("provider") or ""),
            "chat_model": str(_gw.get("chat_model") or ""),
        }
    except Exception:
        engine = {"available": False, "provider": "", "chat_model": ""}
    with get_connection() as conn:
        assessed_rows = conn.execute(
            "SELECT scientific_field, COUNT(1) AS n,"
            " SUM(CASE WHEN verdict = 'applied' THEN 1 ELSE 0 END) AS applied"
            " FROM learning_assessments WHERE verdict != 'skipped' GROUP BY scientific_field"
        ).fetchall()
        latest = conn.execute(
            "SELECT document_id, title, verdict, mastery, assessed_at"
            " FROM learning_assessments WHERE verdict != 'skipped'"
            " ORDER BY id DESC LIMIT 5"
        ).fetchall()
    assessed_by_field: dict[str, int] = {}
    for r in assessed_rows:
        key = _norm_field(r["scientific_field"])
        assessed_by_field[key] = assessed_by_field.get(key, 0) + int(r["n"])
    total_assessed = sum(assessed_by_field.values())
    total_docs = sum(totals.values())
    fields = []
    for field, total in sorted(totals.items(), key=lambda kv: -kv[1]):
        assessed = assessed_by_field.get(field, 0)
        fields.append(
            {
                "field": field,
                "total": total,
                "assessed": assessed,
                "percent": round(100.0 * assessed / total, 1) if total else 0.0,
            }
        )
    for f in fields:
        f["priority_rank"] = _priority_rank(f["field"])
    fields.sort(key=lambda f: (f["priority_rank"], -f["total"]))
    priority_fields = {
        0: "1 — AI and Information Science",
        1: "1 — AI and Information Science",
        2: "2 — Physics",
        3: "3 — Engineering",
    }
    return {
        "ok": True,
        "enabled": learning_enabled(),
        "calibration_enabled": calibration_enabled(),
        "engine": engine,
        "total": total_docs,
        "assessed": total_assessed,
        "percent": round(100.0 * total_assessed / total_docs, 1) if total_docs else 0.0,
        "fields": fields,
        "priority_order": [priority_fields.get(i, f"rest") for i in range(len(LEARNING_PRIORITY_FIELDS))] or [],
        "priority_note": "Examination order: 1) AI and Information Science, 2) Physics, 3) Engineering — the rest follow in any order (§58).",
        "engine_health": {
            "consecutive_failures": _engine_failure_state["consecutive"],
            "total_failures": _engine_failure_state["total"],
            "last_reason": _engine_failure_state["last_reason"],
            "burn_guard": "engine failures never consume documents (74b)",
        },
        "latest": [dict(r) for r in latest],
    }


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

class LearningWorker:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="learning-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            if not learning_enabled():
                self._stop.wait(3.0)
                continue
            try:
                rec = probe_next()
                if rec is None:
                    self._stop.wait(POLL_INTERVAL_SECONDS)
                else:
                    self._stop.wait(0.1)
            except Exception:
                self._stop.wait(1.0)


_worker = LearningWorker()


def start_learning_worker() -> None:
    _ensure_schema()
    _set_setting("learning_enabled", "on")
    _worker.start()


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

class ToggleRequest(BaseModel):
    enabled: bool


class ProbeRequest(BaseModel):
    document_id: int | None = Field(default=None, ge=1)


class ThresholdRequest(BaseModel):
    applied: float | None = Field(default=None, ge=0.05, le=0.95)
    partial: float | None = Field(default=None, ge=0.01, le=0.5)
    recited: float | None = Field(default=None, ge=0.3, le=0.95)


@router.get("/status")
def api_learning_status() -> dict[str, Any]:
    return learning_status()


# 74d — owner-set gate law of the ladder (his numbers, recorded verbatim):
# Calibration opens at 60% Formative Assessment; HLE at 55% after Calibration;
# Workbench at 50% HLE. A locked stage consumes nothing and explains itself.
LADDER_GATES: dict[str, dict[str, Any]] = {
    "calibration": {
        "requires": "formative_assessment", "threshold": 60.0,
        "rule": "Candidate learner must achieve 60% Formative Assessment to access Calibration",
    },
    "hle": {
        "requires": "calibration", "threshold": 55.0,
        "rule": "Datasets must achieve 55% after calibration to access the HLE — until then, data sets are not yet comprehensive to allow assessment",
    },
    "workbench": {
        "requires": "hle", "threshold": 50.0,
        "rule": "Candidate datasets must achieve 50% HLE to access the workbench",
    },
}
LADDER_MEANINGS: dict[str, str] = {
    "datasets_loaded": "loaded documents in this field ÷ total corpus × 100",
    "datasets_learned": "% of documents examined by the gentle examiner",
    "formative_assessment": "% achieved — average exam mastery over the field's graded exams",
    "calibration": "500-word test on subject matter, % achieved",
    "hle": "% achieved on Humanity's Last Exam (HLE)",
    "workbench": "% of the field's corpus applied in the workbench",
}
LADDER_DISPLAY: dict[str, str] = {
    "datasets_loaded": "Datasets Loaded",
    "datasets_learned": "Datasets Learned",
    "formative_assessment": "Formative Assessment",
    "calibration": "Calibration",
    "hle": "HLE",
    "workbench": "Workbench = % Achieved",
}

_HLE_CATEGORY_TO_FIELD: dict[str, str] = {
    "computer-science": "computer-and-information-sciences",
    "thermodynamics": "physics",
    "law": "political-science",
}


@router.get("/ladder")
def api_learning_ladder() -> dict[str, Any]:
    """74c — the owner's learning-and-assessment path, per scientific field.

    Six stages, % achieved each, from REAL state only (no invented numbers):
      datasets_loaded       field loaded docs ÷ TOTAL corpus × 100 (74f)
      datasets_learned      % of documents examined (assessed / total)
      formative_assessment  % achieved — average exam mastery over graded exams
      calibration           500-word test on subject matter — 0 while paused (38)
      hle                   % achieved on Humanity's Last Exam
      workbench             % of the field's corpus applied — 0 until the rig runs it
    """
    with library_connection("gemma") as conn:
        totals: dict[str, int] = {}
        for r in conn.execute(
            "SELECT COALESCE(NULLIF(TRIM(scientific_field), ''), 'unclassified') AS f, COUNT(1) AS n"
            " FROM documents GROUP BY f"
        ).fetchall():
            key = _norm_field(r["f"])
            totals[key] = totals.get(key, 0) + int(r["n"])
        loaded: dict[str, int] = {}
        for r in conn.execute(
            "SELECT COALESCE(NULLIF(TRIM(scientific_field), ''), 'unclassified') AS f, COUNT(1) AS n"
            " FROM documents d WHERE EXISTS (SELECT 1 FROM chunks c WHERE c.document_id = d.id) GROUP BY f"
        ).fetchall():
            key = _norm_field(r["f"])
            loaded[key] = loaded.get(key, 0) + int(r["n"])
    corpus_total = sum(totals.values())
    exams: dict[str, tuple[int, float]] = {}
    with get_connection() as conn:
        for r in conn.execute(
            "SELECT scientific_field AS f, COUNT(1) AS n, AVG(mastery) AS m"
            " FROM learning_assessments WHERE verdict != 'skipped' GROUP BY scientific_field"
        ).fetchall():
            key = _norm_field(r["f"])
            n, m = exams.get(key, (0, 0.0))
            exams[key] = (n + int(r["n"]), (m * n + float(r["m"] or 0.0) * int(r["n"])) / (n + int(r["n"])))

    cal_on = calibration_enabled()
    cal_by_field: dict[str, tuple[int, float]] = {}
    overall_cal_pct = 0.0
    try:
        cal_raw = _get_setting("calibration_report", "")
        cal_rep = json.loads(cal_raw) if cal_raw else None
        if isinstance(cal_rep, dict) and cal_rep.get("ok"):
            if cal_rep.get("agreement_rate") is not None:
                overall_cal_pct = round(100.0 * float(cal_rep["agreement_rate"]), 1)
            for s in cal_rep.get("samples") or []:
                if not isinstance(s, dict) or s.get("rag_grounding") is None:
                    continue
                sf = _norm_field(s.get("field"))
                match_val = 1.0 if s.get("li_verdict") == s.get("rag_verdict") else float(s.get("rag_grounding") or 0.0)
                cn, cm = cal_by_field.get(sf, (0, 0.0))
                cal_by_field[sf] = (cn + 1, (cm * cn + match_val) / (cn + 1))
    except Exception:
        pass

    hle_by_field: dict[str, tuple[int, float]] = {}
    overall_hle_pct = 0.0
    hle_total_graded = 0
    try:
        from .assessment_pipeline import get_state as _get_ap_state

        ap_state = _get_ap_state()
        if ap_state.get("hle_score") is not None:
            overall_hle_pct = round(100.0 * float(ap_state["hle_score"]), 1)
        hle_total_graded = int(ap_state.get("hle_total") or 0)
        for item in ap_state.get("hle_detail") or []:
            if not isinstance(item, dict) or "correct" not in item:
                continue
            raw_cat = _norm_field(item.get("category") or "")
            mapped = _HLE_CATEGORY_TO_FIELD.get(raw_cat, raw_cat)
            val = 1.0 if item.get("correct") else 0.0
            hn, hm = hle_by_field.get(mapped, (0, 0.0))
            hle_by_field[mapped] = (hn + 1, (hm * hn + val) / (hn + 1))
    except Exception:
        pass

    fields: list[dict[str, Any]] = []
    for field, total in totals.items():
        if field == "unclassified":
            continue  # §59 held out from learning accounting
        n_exams, avg_mastery = exams.get(field, (0, 0.0))
        with_chunks = loaded.get(field, 0)
        cal_n, cal_score = cal_by_field.get(field, (0, 0.0))
        field_cal_pct = (100.0 * cal_score) if (cal_on and cal_n > 0) else 0.0
        hle_n, hle_score_f = hle_by_field.get(field, (0, 0.0))
        field_hle_pct = (100.0 * hle_score_f) if hle_n > 0 else overall_hle_pct
        pcts = {
            "datasets_loaded": 100.0 * with_chunks / corpus_total if corpus_total else 0.0,
            "datasets_learned": 100.0 * n_exams / total if total else 0.0,
            "formative_assessment": 100.0 * avg_mastery,
            "calibration": field_cal_pct,
            "hle": field_hle_pct,
            "workbench": 0.0,
        }
        instrument_notes = {
            "calibration": (
                f"Qualia-Lab calibration active ({cal_n} sample(s) graded)"
                if (cal_on and cal_n > 0)
                else ("Qualia-Lab calibration enabled — ready to run" if cal_on else "instrument paused (38) — toggle Calibration: On to enable")
            ),
            "hle": (
                "⏸️ HLE Assessments & Re-learning: PAUSED by Chief Architect — System assimilating & digesting subject matter."
                if ap_state.get("hle_paused")
                else (
                    f"HLE active — {field_hle_pct:.1f}% achieved ({hle_n if hle_n > 0 else hle_total_graded} question(s) graded)"
                    if hle_total_graded > 0
                    else "HLE ready — click Run HLE sample in the Assessment card below"
                )
            ),
            "workbench": "instrument waits for the rig",
        }
        stage_values = {
            "datasets_loaded": with_chunks,
            "datasets_learned": n_exams,
            "formative_assessment": n_exams * avg_mastery,
            "calibration": cal_n * cal_score if cal_on else 0.0,
            "hle": (hle_n * hle_score_f) if hle_n > 0 else (overall_hle_pct / 100.0 if hle_total_graded > 0 else 0.0),
            "workbench": 0.0,
        }
        stages: dict[str, Any] = {}
        for key, pct in pcts.items():
            stage: dict[str, Any] = {
                "percent": round(max(0.0, min(100.0, pct)), 1),
                "meaning": LADDER_MEANINGS[key],
                "value": stage_values[key],
            }
            if key == "datasets_loaded":
                stage["note"] = f"{with_chunks} loaded ÷ {corpus_total} total corpus × 100"
            elif key in instrument_notes:
                stage["note"] = instrument_notes[key]
            gate = LADDER_GATES.get(key)
            if gate:
                current = pcts[gate["requires"]]
                stage["gate"] = {
                    "requires": gate["requires"],
                    "requires_display": LADDER_DISPLAY[gate["requires"]],
                    "threshold": gate["threshold"],
                    "current": round(current, 1),
                    "open": bool(current >= gate["threshold"]),
                    "rule": gate["rule"],
                }
            stages[key] = stage
        fields.append(
            {
                "field": field,
                "display": field.replace("-", " ").upper(),
                "priority_rank": _priority_rank(field),
                "total": total,
                "stages": stages,
            }
        )
    fields.sort(key=lambda f: (f["priority_rank"], -f["total"]))

    next_rest = 4
    for f in fields:
        rank = f["priority_rank"]
        if rank <= 2:
            f["badge"] = "P1"
        elif rank == 3:
            f["badge"] = "P2"
        elif rank == 4:
            f["badge"] = "P3"
        else:
            f["badge"] = f"P{next_rest}"
            next_rest += 1

    classified_total = corpus_total - totals.get("unclassified", 0)
    assessed_total = sum(n for fkey, (n, _m) in exams.items() if fkey != "unclassified")
    mastery_mass_total = sum(n * m for fkey, (n, m) in exams.items() if fkey != "unclassified")
    overall = {
        "corpus_total": corpus_total,
        "classified_total": classified_total,
        "assessed_total": assessed_total,
        "loaded_percent": round(100.0 * sum(loaded.values()) / corpus_total, 1) if corpus_total else 0.0,
        "learned_percent": round(100.0 * assessed_total / classified_total, 1) if classified_total else 0.0,
        "formative_percent": round(100.0 * mastery_mass_total / assessed_total, 1) if assessed_total else 0.0,
        "calibration_percent": overall_cal_pct if cal_on else 0.0,
        "hle_percent": overall_hle_pct,
        "hle_paused": bool(ap_state.get("hle_paused", False)),
        "workbench_percent": 0.0,
    }
    return {
        "ok": True,
        "overall": overall,
        "stages": [
            "datasets_loaded",
            "datasets_learned",
            "formative_assessment",
            "calibration",
            "hle",
            "workbench",
        ],
        "fields": fields,
    }


@router.post("/toggle")
def api_learning_toggle(payload: ToggleRequest) -> dict[str, Any]:
    _set_setting("learning_enabled", "off")
    return {"ok": True, "enabled": False, "note": "The 1/2-page document self-exam loop is retired; HLE is the active assessment."}


@router.post("/probe")
def api_learning_probe(payload: ProbeRequest) -> dict[str, Any]:
    """Examine one document now — the owner's 'watch her learn' button."""
    document_id = payload.document_id
    if document_id is None:
        record = probe_next()
        if record is None:
            raise HTTPException(status_code=404, detail="No unexamined documents in the recent window — every loaded document has been assessed.")
        return {"ok": True, "result": record}
    record = probe_document(int(document_id))
    if record is None:
        raise HTTPException(status_code=404, detail=f"Document {document_id} could not be examined (missing or no readable text).")
    return {"ok": True, "result": record}


def _regrade_all(applied_t: float, partial_t: float, recited_t: float) -> int:
    """Re-apply the verdict function to every stored assessment (§37): the
    thresholds DEFINE the verdicts, so calibrating them must re-grade the
    existing exam records — the index reflects the calibrated examiner.
    Returns the number of rows re-graded."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, grounding_score, verbatim_score, mastery, verdict"
            " FROM learning_assessments"
        ).fetchall()
        changed = 0
        for row in rows:
            if str(row["verdict"]) == "skipped":
                continue
            grounding = float(row["grounding_score"] or 0.0)
            verbatim = float(row["verbatim_score"] or 0.0)
            mastery = grounding * max(0.3, 1.0 - (verbatim - recited_t)) if verbatim > recited_t else grounding
            if mastery >= applied_t:
                verdict = "applied"
            elif verbatim > recited_t:
                verdict = "recited"
            elif grounding > partial_t:
                verdict = "partial"
            else:
                verdict = "not-learned"
            if verdict != str(row["verdict"]):
                conn.execute(
                    "UPDATE learning_assessments SET verdict = ?, mastery = ? WHERE id = ?",
                    (verdict, round(mastery, 4), int(row["id"])),
                )
                changed += 1
        conn.commit()
    return changed


@router.post("/thresholds")
def api_learning_thresholds(payload: ThresholdRequest) -> dict[str, Any]:
    """Persist calibration thresholds (§37) and re-grade every stored exam
    with the new verdict function. Omitted values keep their current setting."""
    before = _grade_thresholds()
    if payload.applied is not None:
        _set_setting("applied_threshold", str(min(0.95, max(0.05, float(payload.applied)))))
    if payload.partial is not None:
        _set_setting("partial_threshold", str(min(0.5, max(0.01, float(payload.partial)))))
    if payload.recited is not None:
        _set_setting("recited_verbatim", str(min(0.95, max(0.3, float(payload.recited)))))
    applied_t, partial_t, recited_t = _grade_thresholds()
    regraded = 0
    if before != (applied_t, partial_t, recited_t):
        regraded = _regrade_all(applied_t, partial_t, recited_t)
    return {
        "ok": True,
        "applied": applied_t,
        "partial": partial_t,
        "recited": recited_t,
        "regraded_records": regraded,
    }


# ---------------------------------------------------------------------------
# Calibration (§37) — Learning Index vs the Qualia Lab instrument
# ---------------------------------------------------------------------------

class CalibrationRequest(BaseModel):
    samples: int = Field(default=6, ge=1, le=20)


# One calibration at a time — full-RAG samples are heavy on the small machine.
_calibration_lock = threading.Lock()
_calibration_thread: threading.Thread | None = None


def _rag_answer_light(question: str, scientific_field: str | None) -> dict[str, Any] | None:
    """Path B of calibration, light instrument (§37 memory lesson).

    The full run_autonomous_chat pipeline (session store, summaries, qualia
    dynamics) pushed this machine past 5 GB and into swap. The Qualia Lab's
    epistemology — retrieve from the library, answer grounded, score with
    its own scorer — needs none of that ceremony: FTS retrieval + ONE
    gateway call per sample. Same questions, same shared grader, honest
    comparison, survivable footprint. The deep pipeline returns on the new rig.
    """
    from .retrieval import search_chunks

    with get_connection() as conn:
        rows = search_chunks(
            conn,
            query=question,
            limit=4,
            scientific_field=scientific_field or None,
        )
    context = "\n\n---\n\n".join(
        str(r.get("content") or "")[:1500] for r in rows
    ).strip()
    if not context:
        return None
    citations = sorted(
        {str(r.get("source_id") or "").strip() for r in rows if str(r.get("source_id") or "").strip()}
    )
    try:
        answer = get_gateway().chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are Sentinel answering an examination question. Use the "
                        "provided library context, answer in your own words, be concise."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Library context:\n{context}\n\nQuestion: {question}",
                },
            ],
            temperature=0.2,
            max_tokens=2048,
        )
    except Exception:
        return None
    return {"answer": answer, "citations": citations}


def _run_calibration(samples: int) -> dict[str, Any]:
    """Re-examine the most recent Learning-Index-assessed documents through
    the Qualia Lab's own instrument (run_autonomous_chat + its scorer) using
    the SAME exam questions, then compare both instruments on the same
    documents and propose evidence-based threshold adjustments.

    Two answer paths per document, one shared grader:
      Path A (Learning Index, already stored): answer from her own knowledge.
      Path B (Qualia pipeline, live): full RAG answer with library retrieval.

    Small-machine discipline (§37): the regular examiner pauses while this
    runs, garbage is collected between samples, and a live done/total tally
    is written so the status endpoint shows progress.
    """
    # Lazy import: the Qualia scorer lives in playground.py (already loaded
    # by main.py long before this router is ever hit).
    from .playground import _score_playground_response

    import gc

    applied_t, partial_t, recited_t = _grade_thresholds()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT document_id, title, scientific_field, question, verdict,"
            " grounding_score, verbatim_score, mastery"
            " FROM learning_assessments WHERE verdict != 'skipped'"
            " ORDER BY id DESC LIMIT ?",
            (samples,),
        ).fetchall()
    if not rows:
        return {"ok": False, "error": "No assessed documents to calibrate against."}

    def _progress(done: int, total: int) -> None:
        try:
            _set_setting("calibration_progress", json.dumps({"done": done, "total": total}))
        except Exception:
            pass

    _progress(0, len(rows))
    samples_out: list[dict[str, Any]] = []
    for row in rows:
        document_id = int(row["document_id"])
        question = str(row["question"] or "")
        material = _load_probe_material(document_id)
        if material is None or not question:
            continue
        _title, _field, source = material
        rag_grounding = rag_verbatim = None
        rag_verdict = "error"
        qualia_overall = None
        try:
            rag = _rag_answer_light(question, str(row["scientific_field"] or ""))
            answer = str(rag.get("answer") or "") if rag else ""
            citations = list(rag.get("citations") or []) if rag else []
            if answer:
                _g, _v, _m, rag_verdict = _grade(answer, source)
                rag_grounding, rag_verbatim = _g, _v
                scores = _score_playground_response(
                    question=question, answer=answer, citations=citations, qualia={}
                )
                qualia_overall = round(float(scores.get("overall") or 0.0), 4)
        except Exception as exc:
            rag_verdict = f"error: {exc}"
        samples_out.append(
            {
                "document_id": document_id,
                "title": str(row["title"] or "")[:80],
                "field": str(row["scientific_field"] or ""),
                "li_verdict": str(row["verdict"]),
                "li_mastery": float(row["mastery"] or 0.0),
                "li_grounding": float(row["grounding_score"] or 0.0),
                "li_verbatim": float(row["verbatim_score"] or 0.0),
                "rag_verdict": rag_verdict,
                "rag_grounding": rag_grounding,
                "rag_verbatim": rag_verbatim,
                "qualia_overall": qualia_overall,
            }
        )
        _progress(len(samples_out), len(rows))
        gc.collect()

    graded = [s for s in samples_out if s["rag_grounding"] is not None]
    agreement = sum(1 for s in graded if s["li_verdict"] == s["rag_verdict"])

    report: dict[str, Any] = {
        "ok": True,
        "mode": "light-rag (deep full-pipeline deferred to the new rig — §37 memory lesson)",
        "thresholds_current": {"applied": applied_t, "partial": partial_t, "recited": recited_t},
        "samples_requested": samples,
        "samples_graded": len(graded),
        "verdict_agreement": agreement,
        "agreement_rate": round(agreement / len(graded), 3) if graded else None,
        "samples": samples_out,
    }

    if len(graded) >= 4:
        mean_li = sum(s["li_mastery"] for s in graded) / len(graded)
        mean_rag = sum(float(s["rag_grounding"]) for s in graded) / len(graded)
        li_applied_rate = sum(1 for s in graded if s["li_verdict"] == "applied") / len(graded)
        rag_support_rate = sum(1 for s in graded if float(s["rag_grounding"]) >= applied_t) / len(graded)
        verbatims = sorted(float(s["li_verbatim"]) for s in graded)
        median_verbatim = verbatims[len(verbatims) // 2]

        masteries = sorted(float(s["li_mastery"]) for s in graded)
        target_share = min(0.85, max(0.15, rag_support_rate))
        idx = min(len(masteries) - 1, max(0, round((1.0 - target_share) * len(masteries))))
        proposed_applied = round(min(0.45, max(0.10, masteries[idx])), 3)
        change = abs(proposed_applied - applied_t)
        recommendation: dict[str, Any] = {
            "mean_li_mastery": round(mean_li, 4),
            "mean_rag_grounding": round(mean_rag, 4),
            "li_applied_rate": round(li_applied_rate, 3),
            "rag_support_rate": round(rag_support_rate, 3),
            "median_li_verbatim": round(median_verbatim, 4),
            "proposed_applied_threshold": proposed_applied,
            "current_applied_threshold": applied_t,
            "recommendation": (
                "keep current"
                if change < 0.03
                else ("lower applied threshold" if proposed_applied < applied_t else "raise applied threshold")
            ),
            "note": "Proposed from quantile matching against the Qualia pipeline's retrieval-supported answer rate on the same documents. Apply via POST /api/learning/thresholds.",
        }
        if median_verbatim > recited_t:
            recommendation["proposed_recited_threshold"] = round(min(0.9, recited_t + 0.1), 3)
            recommendation["note"] += " Recitation boundary raised: median verbatim overlap sits above the current recited cutoff."
        qualia_scores = [s["qualia_overall"] for s in graded if s["qualia_overall"] is not None]
        if qualia_scores:
            recommendation["mean_qualia_overall"] = round(sum(qualia_scores) / len(qualia_scores), 4)
        report["calibration"] = recommendation

        history = _get_setting("calibration_history", "[]")
        try:
            entries = json.loads(history)
        except Exception:
            entries = []
        entries.append(
            {
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "samples_graded": len(graded),
                "agreement_rate": report["agreement_rate"],
                "recommendation": recommendation.get("recommendation"),
                "proposed_applied_threshold": recommendation.get("proposed_applied_threshold"),
            }
        )
        _set_setting("calibration_history", json.dumps(entries[-20:], ensure_ascii=True))
    return report


@router.post("/calibrate")
def api_learning_calibrate(payload: CalibrationRequest) -> dict[str, Any]:
    """Start a Learning Index vs Qualia Lab calibration as a background job."""
    global _calibration_thread
    if not calibration_enabled():
        raise HTTPException(
            status_code=403,
            detail="Calibration is paused (manual toggle, §38). Enable it via POST /api/learning/calibration-toggle or the dashboard button when there is power to spare.",
        )
    if not _calibration_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A calibration run is already in progress — check /api/learning/calibrate/status.")
    _calibration_lock.release()
    state = _get_setting("calibration_state", "idle")
    if state == "running" and not (_calibration_thread is not None and _calibration_thread.is_alive()):
        _set_setting("calibration_state", "interrupted")
        state = "interrupted"
    if state == "running":
        raise HTTPException(status_code=409, detail="A calibration run is already in progress — check /api/learning/calibrate/status.")
    _set_setting("calibration_state", "running")

    def _job() -> None:
        try:
            report = _run_calibration(int(payload.samples))
            _set_setting("calibration_report", json.dumps(report, ensure_ascii=True))
            _set_setting("calibration_state", "done" if report.get("ok") else "error")
        except Exception as exc:
            _set_setting("calibration_report", json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True))
            _set_setting("calibration_state", "error")

    _calibration_thread = threading.Thread(target=_job, name="learning-calibration", daemon=True)
    _calibration_thread.start()
    return {"ok": True, "started": True, "samples": int(payload.samples), "status_endpoint": "/api/learning/calibrate/status"}


@router.post("/calibration-toggle")
def api_learning_calibration_toggle(payload: ToggleRequest) -> dict[str, Any]:
    """Manual calibration switch (§38): OFF until toggled on. Persisted."""
    _set_setting("calibration_enabled", "on" if payload.enabled else "off")
    return {"ok": True, "calibration_enabled": payload.enabled}


@router.get("/exams")
def api_learning_exams(
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    """Recent graded exams for the Learning workspace's log table."""
    _ensure_schema()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT verdict, title, question, mastery, assessed_at FROM learning_assessments"
            " WHERE verdict != 'skipped' ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {"ok": True, "exams": [dict(r) for r in rows]}


@router.get("/calibrate/status")
def api_learning_calibrate_status() -> dict[str, Any]:
    """Latest calibration run: state + full report when done."""
    state = _get_setting("calibration_state", "idle")
    if state == "running":
        thread_alive = _calibration_thread is not None and _calibration_thread.is_alive()
        if not thread_alive:
            _set_setting("calibration_state", "interrupted")
            state = "interrupted"
    report_raw = _get_setting("calibration_report", "")
    report: dict[str, Any] | None = None
    if report_raw:
        try:
            report = json.loads(report_raw)
        except Exception:
            report = None
    return {"ok": True, "state": state, "report": report}
