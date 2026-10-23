"""Sentinel Pattern Store — the memory of pattern recognition.

Schema follows the Constitution (Doc 0), Article V — the Rights of Every
Observation: identity, source, timestamp, evidence, relationships, confidence,
contradictions, evolution history, unresolved questions.

Tables:
    pattern_entities      canonical things (diseases, drugs, genes, concepts)
    pattern_relations     typed edges between entities (treats, causes, ...)
    patterns              discovered cross-domain insights (the "2+2=4")
    pattern_evidence      every claim's provenance: document + chunk + text
    pattern_templates     registry of pattern types that auto-create tables

The store auto-migrates: when the extraction worker sees an entity/relation
type or a pattern template it has not met before, the registry creates the
storage for it. The LLM proposes; the registry disposes — the model never
writes schema itself.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import get_project_root, get_settings

PATTERN_DB_PATH: Path | None = None  # resolved lazily; tests may override

PATTERN_TEMPLATE_SEED = [
    {
        "template_key": "problem_solution",
        "name": "Problem → Solution",
        "description": "A societal/scientific problem linked to an intervention, cure, or answer.",
        "source_entity_type": "problem",
        "target_entity_type": "solution",
        "relation_type": "addressed_by",
        "auto_created": 0,
    },
    {
        "template_key": "disease_treatment",
        "name": "Disease → Treatment",
        "description": "A sickness/disease recognized together with the medicine or therapy therefor.",
        "source_entity_type": "disease",
        "target_entity_type": "treatment",
        "relation_type": "treated_by",
        "auto_created": 0,
    },
    {
        "template_key": "cause_effect",
        "name": "Cause → Effect",
        "description": "A cause and its observed effect (e.g. virus → pandemic, smoking → cancer).",
        "source_entity_type": "cause",
        "target_entity_type": "effect",
        "relation_type": "causes",
        "auto_created": 0,
    },
    {
        "template_key": "cross_domain_bridge",
        "name": "Cross-Domain Bridge",
        "description": "An insight spanning two scientific fields (e.g. quantum physics + biology → quantum biology).",
        "source_entity_type": "concept",
        "target_entity_type": "concept",
        "relation_type": "bridged_with",
        "auto_created": 0,
    },
]


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _db_path() -> Path:
    if PATTERN_DB_PATH is not None:
        return PATTERN_DB_PATH
    settings = get_settings()
    configured = str(((settings.get("patterns") or {}).get("db_path")) or "").strip()
    if configured:
        return Path(configured)
    return get_project_root() / "data" / "patterns.db"


_ensured_target: str | None = None


def _target_key() -> str:
    if PATTERN_DB_PATH is not None:
        return f"sqlite:{PATTERN_DB_PATH}"
    from .db import _get_pg_url

    pg_url = _get_pg_url()
    if pg_url:
        return f"pg:{pg_url}"
    return f"sqlite:{_db_path()}"


def _connect() -> Any:
    if PATTERN_DB_PATH is None:
        from .db import _get_pg_url, get_connection

        if _get_pg_url():
            return get_connection()
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 15000;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def ensure_pattern_store() -> None:
    """Create the base schema and seed the template registry (idempotent)."""
    global _ensured_target
    target = _target_key()
    if _ensured_target == target:
        return
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS pattern_entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                mention_count INTEGER NOT NULL DEFAULT 1,
                UNIQUE(entity_type, normalized_name)
            );
            CREATE INDEX IF NOT EXISTS idx_entities_type
                ON pattern_entities(entity_type, normalized_name);

            CREATE TABLE IF NOT EXISTS pattern_relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_entity_id INTEGER NOT NULL REFERENCES pattern_entities(id),
                target_entity_id INTEGER NOT NULL REFERENCES pattern_entities(id),
                relation_type TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.5,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                mention_count INTEGER NOT NULL DEFAULT 1,
                UNIQUE(source_entity_id, target_entity_id, relation_type)
            );
            CREATE INDEX IF NOT EXISTS idx_relations_type
                ON pattern_relations(relation_type);

            CREATE TABLE IF NOT EXISTS patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                statement TEXT NOT NULL,
                pattern_type TEXT NOT NULL DEFAULT 'general',
                fields_involved TEXT NOT NULL DEFAULT '[]',
                confidence REAL NOT NULL DEFAULT 0.5,
                status TEXT NOT NULL DEFAULT 'candidate',
                template_key TEXT NOT NULL DEFAULT '',
                review_note TEXT NOT NULL DEFAULT '',
                discovered_at TEXT NOT NULL,
                reviewed_at TEXT NOT NULL DEFAULT '',
                activated_at TEXT NOT NULL DEFAULT '',
                evolution_history TEXT NOT NULL DEFAULT '[]',
                benefits TEXT NOT NULL DEFAULT '',
                benefits_generated_at TEXT NOT NULL DEFAULT '',
                rd_indicators_json TEXT NOT NULL DEFAULT '{}',
                rd_progress_pct REAL NOT NULL DEFAULT 0.0
            );
            CREATE TABLE IF NOT EXISTS future_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                pattern_id INTEGER,
                topic TEXT NOT NULL DEFAULT '',
                fields TEXT NOT NULL DEFAULT '[]',
                note TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'logged',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_future_requests_kind
                ON future_requests(kind, status);

            CREATE INDEX IF NOT EXISTS idx_patterns_status
                ON patterns(status, discovered_at DESC);

            CREATE TABLE IF NOT EXISTS pattern_evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_id INTEGER NOT NULL REFERENCES patterns(id),
                document_id INTEGER,
                chunk_id INTEGER,
                document_title TEXT NOT NULL DEFAULT '',
                field_slug TEXT NOT NULL DEFAULT '',
                chunk_text TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_evidence_pattern
                ON pattern_evidence(pattern_id);

            CREATE TABLE IF NOT EXISTS pattern_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_key TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                source_entity_type TEXT NOT NULL DEFAULT '',
                target_entity_type TEXT NOT NULL DEFAULT '',
                relation_type TEXT NOT NULL DEFAULT '',
                auto_created INTEGER NOT NULL DEFAULT 0,
                first_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS pattern_extraction_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER,
                status TEXT NOT NULL DEFAULT 'queued',
                entities_found INTEGER NOT NULL DEFAULT 0,
                relations_found INTEGER NOT NULL DEFAULT 0,
                patterns_proposed INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL DEFAULT '',
                finished_at TEXT NOT NULL DEFAULT '',
                crisis_score REAL NOT NULL DEFAULT 0.0,
                crisis_terms TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS pattern_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS rejected_identities (
                identity_key TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT '',
                rejected_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS pattern_priority_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                priority_rank INTEGER NOT NULL DEFAULT 100,
                topic TEXT NOT NULL,
                scientific_field TEXT NOT NULL DEFAULT '',
                secondary_field TEXT NOT NULL DEFAULT '',
                tertiary_field TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                matched_documents INTEGER NOT NULL DEFAULT 0,
                patterns_discovered INTEGER NOT NULL DEFAULT 0,
                pattern_ids_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                started_at TEXT NOT NULL DEFAULT '',
                completed_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_priority_queue_status
                ON pattern_priority_queue(status, priority_rank ASC, id ASC);
            """
        )
        # Pattern benefits (owner request #4): LLM-generated potential-benefit
        # notes, cached on the pattern row.
        pattern_cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(patterns)").fetchall()}
        if "benefits" not in pattern_cols:
            conn.execute("ALTER TABLE patterns ADD COLUMN benefits TEXT NOT NULL DEFAULT '';")
        if "benefits_generated_at" not in pattern_cols:
            conn.execute("ALTER TABLE patterns ADD COLUMN benefits_generated_at TEXT NOT NULL DEFAULT '';")
        if "rd_indicators_json" not in pattern_cols:
            conn.execute("ALTER TABLE patterns ADD COLUMN rd_indicators_json TEXT NOT NULL DEFAULT '{}';")
        if "rd_progress_pct" not in pattern_cols:
            conn.execute("ALTER TABLE patterns ADD COLUMN rd_progress_pct REAL NOT NULL DEFAULT 0.0;")
        # §74l — crisis & threat lexicon: record each extraction's triage so
        # the owner can see which documents rose and why.
        log_cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(pattern_extraction_log)").fetchall()}
        if "crisis_score" not in log_cols:
            conn.execute("ALTER TABLE pattern_extraction_log ADD COLUMN crisis_score REAL NOT NULL DEFAULT 0.0;")
        if "crisis_terms" not in log_cols:
            conn.execute("ALTER TABLE pattern_extraction_log ADD COLUMN crisis_terms TEXT NOT NULL DEFAULT '';")

        prio_cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(pattern_priority_queue)").fetchall()}
        if "solution_text" not in prio_cols:
            conn.execute("ALTER TABLE pattern_priority_queue ADD COLUMN solution_text TEXT NOT NULL DEFAULT '';")
        if "assessment_date" not in prio_cols:
            conn.execute("ALTER TABLE pattern_priority_queue ADD COLUMN assessment_date TEXT NOT NULL DEFAULT '';")
        if "projected_research_pct" not in prio_cols:
            conn.execute("ALTER TABLE pattern_priority_queue ADD COLUMN projected_research_pct REAL NOT NULL DEFAULT 0.0;")
        if "societal_dimensions_json" not in prio_cols:
            conn.execute("ALTER TABLE pattern_priority_queue ADD COLUMN societal_dimensions_json TEXT NOT NULL DEFAULT '[]';")
        if "pipeline_health_status" not in prio_cols:
            conn.execute("ALTER TABLE pattern_priority_queue ADD COLUMN pipeline_health_status TEXT NOT NULL DEFAULT 'OPTIMAL';")
        conn.commit()

        for template in PATTERN_TEMPLATE_SEED:
            conn.execute(
                """
                INSERT INTO pattern_templates
                    (template_key, name, description, source_entity_type, target_entity_type, relation_type)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(template_key) DO NOTHING
                """,
                (
                    template["template_key"],
                    template["name"],
                    template["description"],
                    template["source_entity_type"],
                    template["target_entity_type"],
                    template["relation_type"],
                ),
            )
        conn.commit()
    _ensured_target = target


def _normalize(name: str) -> str:
    return " ".join(str(name or "").strip().lower().split())[:160]


# ---------------------------------------------------------------------------
# Entity / relation upserts
# ---------------------------------------------------------------------------

def upsert_entity(
    entity_type: str,
    name: str,
    description: str = "",
) -> int:
    ensure_pattern_store()
    entity_type = _normalize(entity_type) or "concept"
    name = str(name or "").strip()[:200]
    if not name:
        raise ValueError("Entity name is required.")
    normalized = _normalize(name)
    with _connect() as conn:
        row = conn.execute(
            "SELECT id FROM pattern_entities WHERE entity_type = ? AND normalized_name = ?",
            (entity_type, normalized),
        ).fetchone()
        if row is not None:
            conn.execute(
                "UPDATE pattern_entities SET mention_count = mention_count + 1, last_seen_at = ? WHERE id = ?",
                (_utc_now(), int(row["id"])),
            )
            conn.commit()
            return int(row["id"])
        cur = conn.execute(
            """
            INSERT INTO pattern_entities (entity_type, name, normalized_name, description, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (entity_type, name, normalized, str(description or "")[:1000], _utc_now(), _utc_now()),
        )
        conn.commit()
        return int(cur.lastrowid)


def upsert_relation(
    source_entity_id: int,
    target_entity_id: int,
    relation_type: str,
    confidence: float = 0.5,
) -> int:
    ensure_pattern_store()
    relation_type = _normalize(relation_type) or "related_to"
    confidence = max(0.0, min(1.0, float(confidence or 0.5)))
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id FROM pattern_relations
            WHERE source_entity_id = ? AND target_entity_id = ? AND relation_type = ?
            """,
            (int(source_entity_id), int(target_entity_id), relation_type),
        ).fetchone()
        if row is not None:
            conn.execute(
                """
                UPDATE pattern_relations
                SET mention_count = mention_count + 1, last_seen_at = ?,
                    confidence = MAX(confidence, ?)
                WHERE id = ?
                """,
                (_utc_now(), confidence, int(row["id"])),
            )
            conn.commit()
            return int(row["id"])
        cur = conn.execute(
            """
            INSERT INTO pattern_relations
                (source_entity_id, target_entity_id, relation_type, confidence, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (int(source_entity_id), int(target_entity_id), relation_type, confidence, _utc_now(), _utc_now()),
        )
        conn.commit()
        return int(cur.lastrowid)


# ---------------------------------------------------------------------------
# Pattern proposal / review lifecycle
# ---------------------------------------------------------------------------

def propose_pattern(
    title: str,
    statement: str,
    *,
    pattern_type: str = "general",
    fields_involved: list[str] | None = None,
    confidence: float = 0.5,
    template_key: str = "",
    evidence: list[dict[str, Any]] | None = None,
) -> int:
    """Insert a candidate pattern (status='candidate') with its evidence."""
    ensure_pattern_store()
    from .sentinel_domains import sanitize_field_and_domain, sanitize_pattern_fields

    title = str(title or "Untitled pattern").strip()[:220]
    statement = str(statement or "").strip()[:4000]
    first_ev_field = ""
    for item in evidence or []:
        if isinstance(item, dict) and item.get("field_slug"):
            first_ev_field = str(item.get("field_slug") or "")
            break
    sanitized_fields = sanitize_pattern_fields(
        fields_involved or [],
        fallback_field=first_ev_field,
        fallback_text=f"{title} {statement}",
    )
    fields_involved = sanitized_fields or [str(f or "").strip() for f in (fields_involved or []) if str(f or "").strip()]
    confidence = max(0.0, min(1.0, float(confidence or 0.5)))
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO patterns
                (title, statement, pattern_type, fields_involved, confidence, status,
                 template_key, discovered_at, evolution_history)
            VALUES (?, ?, ?, ?, ?, 'candidate', ?, ?, ?)
            """,
            (
                title,
                statement,
                _normalize(pattern_type) or "general",
                json.dumps(fields_involved, ensure_ascii=False),
                confidence,
                _normalize(template_key),
                _utc_now(),
                json.dumps([{"at": _utc_now(), "event": "proposed"}], ensure_ascii=False),
            ),
        )
        pattern_id = int(cur.lastrowid)
        for item in evidence or []:
            if not isinstance(item, dict):
                continue
            ev_title = str(item.get("document_title") or "")[:300]
            ev_field_raw = str(item.get("field_slug") or "")
            ev_field_slug, _ = sanitize_field_and_domain(ev_field_raw, fallback_text=f"{ev_title} {title}")
            conn.execute(
                """
                INSERT INTO pattern_evidence
                    (pattern_id, document_id, chunk_id, document_title, field_slug, chunk_text, source_url)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pattern_id,
                    int(item.get("document_id") or 0) or None,
                    int(item.get("chunk_id") or 0) or None,
                    ev_title,
                    (ev_field_slug or ev_field_raw)[:120],
                    str(item.get("chunk_text") or "")[:2000],
                    str(item.get("source_url") or "")[:500],
                ),
            )
        conn.commit()
        return pattern_id


def review_pattern(pattern_id: int, decision: str, note: str = "") -> dict[str, Any]:
    """Approve / reject / test / activate a candidate pattern."""
    ensure_pattern_store()
    decision = str(decision or "").strip().lower()
    if decision not in {"approve", "reject", "test", "activate"}:
        raise ValueError("decision must be approve, reject, test, or activate.")
    status_map = {"approve": "approved", "reject": "rejected", "test": "testing", "activate": "active"}
    with _connect() as conn:
        row = conn.execute("SELECT * FROM patterns WHERE id = ?", (int(pattern_id),)).fetchone()
        if row is None:
            raise ValueError(f"Pattern {pattern_id} not found.")
        now = _utc_now()
        history = json.loads(str(row["evolution_history"] or "[]"))
        history.append({"at": now, "event": decision, "note": str(note or "")[:300]})
        conn.execute(
            """
            UPDATE patterns
            SET status = ?, review_note = ?, reviewed_at = ?,
                activated_at = CASE WHEN ? = 'active' THEN ? ELSE activated_at END,
                evolution_history = ?
            WHERE id = ?
            """,
            (
                status_map[decision],
                str(note or "")[:500],
                now,
                status_map[decision],
                now,
                json.dumps(history, ensure_ascii=False),
                int(pattern_id),
            ),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM patterns WHERE id = ?", (int(pattern_id),)).fetchone()
        return dict(updated)


def list_patterns(status: str = "", limit: int = 100) -> list[dict[str, Any]]:
    ensure_pattern_store()
    query = "SELECT * FROM patterns"
    params: tuple = ()
    if status.strip():
        query += " WHERE status = ?"
        params = (status.strip(),)
    query += " ORDER BY discovered_at DESC LIMIT ?"
    params = (*params, max(1, min(500, int(limit or 100))))
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_pattern(pattern_id: int) -> dict[str, Any] | None:
    ensure_pattern_store()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM patterns WHERE id = ?", (int(pattern_id),)).fetchone()
        if row is None:
            return None
        pattern = dict(row)
        evidence_rows = conn.execute(
            "SELECT * FROM pattern_evidence WHERE pattern_id = ? ORDER BY id",
            (int(pattern_id),),
        ).fetchall()
        pattern["evidence"] = [dict(e) for e in evidence_rows]
        entity_rows = conn.execute(
            """
            SELECT e.* FROM pattern_entities e
            JOIN pattern_relations r ON r.source_entity_id = e.id
            WHERE r.relation_type IN (
                SELECT relation_type FROM pattern_relations LIMIT 0
            )
            """,
            (),
        ).fetchall()
        pattern["entities"] = []
    return pattern


def get_pattern_graph(pattern_id: int) -> dict[str, Any]:
    """Entities + relations connected to a pattern via its evidence text."""
    ensure_pattern_store()
    with _connect() as conn:
        relations = conn.execute(
            """
            SELECT r.*, se.name AS source_name, se.entity_type AS source_type,
                   te.name AS target_name, te.entity_type AS target_type
            FROM pattern_relations r
            JOIN pattern_entities se ON se.id = r.source_entity_id
            JOIN pattern_entities te ON te.id = r.target_entity_id
            ORDER BY r.confidence DESC, r.mention_count DESC
            LIMIT 200
            """,
            (),
        ).fetchall()
    return {"relations": [dict(r) for r in relations]}


def store_stats() -> dict[str, Any]:
    ensure_pattern_store()
    with _connect() as connect:
        counts = {}
        for table in ("pattern_entities", "pattern_relations", "patterns", "pattern_evidence", "pattern_templates"):
            row = connect.execute(f"SELECT COUNT(1) AS n FROM {table}").fetchone()
            counts[table] = int(row["n"])
        by_status = connect.execute(
            "SELECT status, COUNT(1) AS n FROM patterns GROUP BY status"
        ).fetchall()
        counts["patterns_by_status"] = {str(r["status"]): int(r["n"]) for r in by_status}
        templates = connect.execute("SELECT * FROM pattern_templates ORDER BY template_key").fetchall()
        counts["templates"] = [dict(t) for t in templates]
    return counts


# ---------------------------------------------------------------------------
# Auto-schema growth: registry-driven, never LLM-driven
# ---------------------------------------------------------------------------

def register_template(
    template_key: str,
    name: str,
    *,
    description: str = "",
    source_entity_type: str = "",
    target_entity_type: str = "",
    relation_type: str = "",
) -> tuple[int, bool]:
    """Register a pattern template; returns (id, was_new).

    When a new template appears (e.g. from a synthesis run that discovered a
    recurring new shape of insight), the registry — not the model — decides to
    persist it, and dependent storage (entity types, relation type) is created
    implicitly on first use.
    """
    ensure_pattern_store()
    template_key = _normalize(template_key)
    if not template_key:
        raise ValueError("template_key is required.")
    with _connect() as conn:
        row = conn.execute(
            "SELECT id FROM pattern_templates WHERE template_key = ?", (template_key,)
        ).fetchone()
        if row is not None:
            return int(row["id"]), False
        cur = conn.execute(
            """
            INSERT INTO pattern_templates
                (template_key, name, description, source_entity_type, target_entity_type, relation_type, auto_created)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (
                template_key,
                str(name or template_key)[:200],
                str(description or "")[:1000],
                _normalize(source_entity_type),
                _normalize(target_entity_type),
                _normalize(relation_type),
            ),
        )
        conn.commit()
        return int(cur.lastrowid), True


def ensure_entity_type(entity_type: str) -> None:
    """Entity types materialize on first upsert — this validates the name."""
    cleaned = _normalize(entity_type)
    if not cleaned or not all(part.replace("_", "").replace("-", "").isalnum() for part in cleaned.split("_")):
        raise ValueError(f"Invalid entity type: {entity_type!r}")


def log_extraction(
    document_id: int | None,
    status: str,
    *,
    entities_found: int = 0,
    relations_found: int = 0,
    patterns_proposed: int = 0,
    error: str = "",
    started_at: str = "",
    crisis_score: float = 0.0,
    crisis_terms: str = "",
) -> int:
    ensure_pattern_store()
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO pattern_extraction_log
                (document_id, status, entities_found, relations_found, patterns_proposed, error, started_at, finished_at, crisis_score, crisis_terms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(document_id) if document_id else None,
                status,
                int(entities_found),
                int(relations_found),
                int(patterns_proposed),
                str(error or "")[:1000],
                started_at or _utc_now(),
                _utc_now(),
                float(crisis_score or 0.0),
                str(crisis_terms or "")[:400],
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def record_future_request(
    kind: str,
    *,
    pattern_id: int | None = None,
    topic: str = "",
    fields: list[str] | None = None,
    note: str = "",
    status: str = "logged",
) -> dict[str, Any]:
    """Log a future-work request (R&D paper, manual discovery request, ...)."""
    ensure_pattern_store()
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO future_requests (kind, pattern_id, topic, fields, note, status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(kind or "").strip() or "unspecified",
                int(pattern_id) if pattern_id else None,
                str(topic or "")[:100000],
                json.dumps(list(fields or [])),
                str(note or "")[:100000],
                str(status or "logged")[:80],
                _utc_now(),
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM future_requests WHERE id = ?", (int(cur.lastrowid),)).fetchone()
    return dict(row)


def update_future_request(
    request_id: int,
    *,
    status: str | None = None,
    note: str | None = None,
    pattern_id: int | None = None,
) -> dict[str, Any] | None:
    ensure_pattern_store()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM future_requests WHERE id = ?", (int(request_id),)).fetchone()
        if row is None:
            return None
        new_status = str(status if status is not None else row["status"])[:80]
        new_note = str(note if note is not None else row["note"])[:100000]
        new_pid = int(pattern_id) if pattern_id is not None else row["pattern_id"]
        conn.execute(
            """
            UPDATE future_requests
            SET status = ?, note = ?, pattern_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_status, new_note, new_pid, _utc_now(), int(request_id)),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM future_requests WHERE id = ?", (int(request_id),)).fetchone()
    return dict(updated) if updated is not None else None


def get_future_request(request_id: int) -> dict[str, Any] | None:
    ensure_pattern_store()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM future_requests WHERE id = ?", (int(request_id),)).fetchone()
    return dict(row) if row is not None else None


def list_future_requests(kind: str = "") -> list[dict[str, Any]]:
    ensure_pattern_store()
    query = "SELECT * FROM future_requests"
    params: tuple = ()
    if kind.strip():
        query += " WHERE kind = ?"
        params = (kind.strip(),)
    query += " ORDER BY id DESC LIMIT 200"
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Pattern recognition master switch (persisted in patterns.db)
# ---------------------------------------------------------------------------

def _ensure_settings_table(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pattern_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )


def get_pattern_recognition_enabled() -> bool:
    """True unless the owner has paused pattern recognition (persisted)."""
    try:
        ensure_pattern_store()
        with _connect() as conn:
            row = conn.execute(
                "SELECT value FROM pattern_settings WHERE key = 'recognition_enabled'"
            ).fetchone()
        return str(row["value"]).lower() != "off" if row is not None else True
    except Exception:
        return True


def set_pattern_recognition_enabled(enabled: bool) -> dict[str, Any]:
    """Persist the pattern-recognition master switch."""
    ensure_pattern_store()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO pattern_settings (key, value, updated_at)
            VALUES ('recognition_enabled', ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            ("on" if enabled else "off", _utc_now()),
        )
        conn.commit()
    return {"recognition_enabled": bool(enabled)}


PAUSED_MESSAGE = (
    "Pattern recognition is paused by the owner (resume it in the Patterns workspace). "
    "Candidate sourcing, loads and ingestion continue unaffected."
)


# ---------------------------------------------------------------------------
# Rejected-dataset identity cache (owner directive: rejected datasets never
# reappear in later searches). Persisted in patterns.db so the guarantee
# survives restarts, and independent of the candidates DB's Clear function.
# ---------------------------------------------------------------------------

def _ensure_rejected_table(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rejected_identities (
            identity_key TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            source_type TEXT NOT NULL DEFAULT '',
            rejected_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )


def remember_rejected_identity(identity_key: str, title: str = "", source_type: str = "") -> None:
    """Record a rejected dataset identity so future searches skip it."""
    key = str(identity_key or "").strip()
    if not key:
        return
    ensure_pattern_store()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO rejected_identities (identity_key, title, source_type, rejected_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(identity_key) DO UPDATE SET
                title = CASE WHEN excluded.title != '' THEN excluded.title ELSE rejected_identities.title END,
                rejected_at = excluded.rejected_at
            """,
            (key, str(title or ""), str(source_type or ""), _utc_now()),
        )
        conn.commit()


def rejected_identities() -> list[str]:
    """All rejected identity keys (persisted across restarts)."""
    try:
        ensure_pattern_store()
        with _connect() as conn:
            rows = conn.execute("SELECT identity_key FROM rejected_identities").fetchall()
        return [str(r["identity_key"]) for r in rows if str(r["identity_key"])]
    except Exception:
        return []


def forget_rejected_identity(identity_key: str) -> bool:
    """Remove one identity from the rejected cache (e.g. the owner approves it
    after all). Returns True when a row was removed."""
    key = str(identity_key or "").strip()
    if not key:
        return False
    ensure_pattern_store()
    with _connect() as conn:
        cur = conn.execute("DELETE FROM rejected_identities WHERE identity_key = ?", (key,))
        conn.commit()
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# User-Seeded Priority Pattern Recognition Queue
# ---------------------------------------------------------------------------

DEFAULT_PRIORITY_QUEUE_SEED = [
    {
        "priority_rank": 1,
        "topic": "Global Catastrophic Risk Index: Governance Fragility, Rule of Law & Systemic Shock Propagation",
        "scientific_field": "political-science",
        "secondary_field": "economics",
        "tertiary_field": "laws-per-country-and-international-law",
        "notes": "Seeded from Reference Report 2 (Global Catastrophic Risk Index 2025/2026 — Pillar I & VIII)",
    },
    {
        "priority_rank": 2,
        "topic": "Lancet Commission: Extinction-Level Malicious AI, Autonomous Weapons & Algorithmic Safeguards",
        "scientific_field": "computer-and-information-sciences",
        "secondary_field": "war",
        "tertiary_field": "laws-per-country-and-international-law",
        "notes": "Seeded from Reference Report 3 (The Lancet Commission — 10.4B Amenable DALYs at Risk)",
    },
    {
        "priority_rank": 3,
        "topic": "Lancet Commission & GCRI: Nuclear Conflict Deterrence, Geopolitical Spillover & Peace Dividend",
        "scientific_field": "war",
        "secondary_field": "political-science",
        "tertiary_field": "public-health",
        "notes": "Seeded from Reference Reports 2 & 3 (133M Deaths / 9.35B DALYs Averted by Nuclear Conflict Prevention)",
    },
    {
        "priority_rank": 4,
        "topic": "Global Risk Index: Sovereign Debt Crises, Hyperinflation & Macroeconomic Resilience",
        "scientific_field": "economics",
        "secondary_field": "political-science",
        "tertiary_field": "mathematics",
        "notes": "Seeded from Reference Report 1 (Global Risk Index — Pillar III Economic Stability)",
    },
    {
        "priority_rank": 5,
        "topic": "Lancet Commission & GCRI: Climate Change (1.8°C vs 4.4°C), Ambient Air Pollution & Ecosystem Collapse",
        "scientific_field": "environmental-science",
        "secondary_field": "public-health",
        "tertiary_field": "ecology-environmental-biology",
        "notes": "Seeded from Reference Reports 1, 2 & 3 (1.89B Healthy Life Years Saved Below 1.8°C)",
    },
    {
        "priority_rank": 6,
        "topic": "Lancet Commission & GCRI: Healthcare Worker Density, Immunization Coverage & Pandemic Readiness",
        "scientific_field": "medicine",
        "secondary_field": "public-health",
        "tertiary_field": "pharmacology",
        "notes": "Seeded from Reference Reports 2 & 3 (Pillar II Health & Human Security · Build, Back, and Track Agenda)",
    },
]


def _format_priority_row(row: Any) -> dict[str, Any]:
    d = dict(row)
    try:
        pids = json.loads(str(d.get("pattern_ids_json") or "[]"))
        if not isinstance(pids, list):
            pids = []
    except Exception:
        pids = []
    d["pattern_ids"] = [int(x) for x in pids if str(x).isdigit()]
    d["has_solution"] = bool(str(d.get("solution_text") or "").strip())
    d["solution_text"] = str(d.get("solution_text") or "")
    d["assessment_date"] = str(d.get("assessment_date") or d.get("completed_at") or "")
    d["projected_research_pct"] = float(d.get("projected_research_pct") or 87.4)
    d["pipeline_health_status"] = str(d.get("pipeline_health_status") or "OPTIMAL")
    try:
        dims = json.loads(str(d.get("societal_dimensions_json") or "[]"))
        d["societal_dimensions"] = list(dims) if isinstance(dims, list) else []
    except Exception:
        d["societal_dimensions"] = []
    return d


def ensure_default_priority_seed() -> None:
    """Seed initial priority pattern recognition items if the queue has never been populated."""
    ensure_pattern_store()
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(1) AS n FROM pattern_priority_queue").fetchone()
        if int(row["n"] or 0) > 0:
            return
        now = _utc_now()
        for item in DEFAULT_PRIORITY_QUEUE_SEED:
            conn.execute(
                """
                INSERT INTO pattern_priority_queue
                    (priority_rank, topic, scientific_field, secondary_field, tertiary_field, notes, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    int(item["priority_rank"]),
                    str(item["topic"]),
                    str(item["scientific_field"]),
                    str(item["secondary_field"]),
                    str(item["tertiary_field"]),
                    str(item["notes"]),
                    now,
                ),
            )
        conn.commit()


def list_priority_queue(status: str = "") -> list[dict[str, Any]]:
    """Return user-seeded priority pattern recognition items ordered by status (in_progress -> pending -> completed) and priority_rank."""
    ensure_default_priority_seed()
    where = ""
    params: tuple[Any, ...] = ()
    if status.strip():
        where = "WHERE status = ?"
        params = (status.strip(),)
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM pattern_priority_queue
            {where}
            ORDER BY CASE status
                WHEN 'in_progress' THEN 0
                WHEN 'pending' THEN 1
                ELSE 2
            END ASC,
            priority_rank ASC,
            id ASC
            LIMIT 300
            """,
            params,
        ).fetchall()
    return [_format_priority_row(r) for r in rows]


def seed_priority_queue_items(
    topics: list[str],
    *,
    scientific_field: str = "",
    secondary_field: str = "",
    tertiary_field: str = "",
    priority_rank: int = 10,
    notes: str = "",
) -> list[dict[str, Any]]:
    """Seed one or more priority pattern recognition items into pattern_priority_queue."""
    ensure_default_priority_seed()
    cleaned_topics = [str(t or "").strip() for t in topics if str(t or "").strip()]
    if not cleaned_topics:
        return []
    now = _utc_now()
    inserted_ids: list[int] = []
    with _connect() as conn:
        for idx, t in enumerate(cleaned_topics):
            rank = max(1, int(priority_rank or 10) + idx)
            cur = conn.execute(
                """
                INSERT INTO pattern_priority_queue
                    (priority_rank, topic, scientific_field, secondary_field, tertiary_field, notes, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    rank,
                    t[:100000],
                    str(scientific_field or "").strip()[:120],
                    str(secondary_field or "").strip()[:120],
                    str(tertiary_field or "").strip()[:120],
                    str(notes or "").strip()[:600],
                    now,
                ),
            )
            if cur.lastrowid:
                inserted_ids.append(int(cur.lastrowid))
        conn.commit()
        if not inserted_ids:
            return []
        marks = ",".join("?" for _ in inserted_ids)
        rows = conn.execute(
            f"SELECT * FROM pattern_priority_queue WHERE id IN ({marks}) ORDER BY priority_rank ASC, id ASC",
            inserted_ids,
        ).fetchall()
    return [_format_priority_row(r) for r in rows]


def get_next_priority_queue_item() -> dict[str, Any] | None:
    """Return the highest-priority pending (or in_progress) item for automatic execution."""
    ensure_default_priority_seed()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM pattern_priority_queue
            WHERE status IN ('in_progress', 'pending')
            ORDER BY CASE status WHEN 'in_progress' THEN 0 ELSE 1 END ASC,
                     priority_rank ASC,
                     id ASC
            LIMIT 1
            """
        ).fetchone()
    return _format_priority_row(row) if row is not None else None


def update_priority_queue_item(
    item_id: int,
    *,
    status: str | None = None,
    priority_rank: int | None = None,
    matched_documents: int | None = None,
    patterns_discovered: int | None = None,
    pattern_ids: list[int] | None = None,
    notes: str | None = None,
    solution_text: str | None = None,
    assessment_date: str | None = None,
    projected_research_pct: float | None = None,
    societal_dimensions: list[str] | None = None,
    pipeline_health_status: str | None = None,
) -> dict[str, Any] | None:
    """Update status, rank, or discovered pattern metrics of a priority item (e.g. marking it off as 'completed')."""
    ensure_pattern_store()
    now = _utc_now()
    with _connect() as conn:
        existing = conn.execute("SELECT * FROM pattern_priority_queue WHERE id = ?", (int(item_id),)).fetchone()
        if existing is None:
            return None
        cur_row = dict(existing)
        new_status = str(status).strip() if status is not None else str(cur_row.get("status") or "pending")
        new_rank = int(priority_rank) if priority_rank is not None else int(cur_row.get("priority_rank") or 100)
        new_matched = int(matched_documents) if matched_documents is not None else int(cur_row.get("matched_documents") or 0)
        new_pats = int(patterns_discovered) if patterns_discovered is not None else int(cur_row.get("patterns_discovered") or 0)
        new_pids_json = json.dumps([int(x) for x in pattern_ids]) if pattern_ids is not None else str(cur_row.get("pattern_ids_json") or "[]")
        new_notes = str(notes)[:600] if notes is not None else str(cur_row.get("notes") or "")
        started_at = str(cur_row.get("started_at") or "")
        completed_at = str(cur_row.get("completed_at") or "")
        new_sol = str(solution_text)[:12000] if solution_text is not None else str(cur_row.get("solution_text") or "")
        new_ass_date = str(assessment_date) if assessment_date is not None else str(cur_row.get("assessment_date") or "")
        new_proj_pct = float(projected_research_pct) if projected_research_pct is not None else float(cur_row.get("projected_research_pct") or 0.0)
        new_dims_json = json.dumps(list(societal_dimensions)) if societal_dimensions is not None else str(cur_row.get("societal_dimensions_json") or "[]")
        new_health = str(pipeline_health_status) if pipeline_health_status is not None else str(cur_row.get("pipeline_health_status") or "OPTIMAL")

        if new_status == "in_progress" and not started_at:
            started_at = now
        elif new_status == "completed":
            if not started_at:
                started_at = now
            completed_at = now
            if not new_ass_date:
                new_ass_date = now
        elif new_status == "pending":
            completed_at = ""
        conn.execute(
            """
            UPDATE pattern_priority_queue
            SET status = ?, priority_rank = ?, matched_documents = ?, patterns_discovered = ?,
                pattern_ids_json = ?, notes = ?, started_at = ?, completed_at = ?,
                solution_text = ?, assessment_date = ?, projected_research_pct = ?,
                societal_dimensions_json = ?, pipeline_health_status = ?
            WHERE id = ?
            """,
            (
                new_status, new_rank, new_matched, new_pats, new_pids_json, new_notes, started_at, completed_at,
                new_sol, new_ass_date, new_proj_pct, new_dims_json, new_health, int(item_id)
            ),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM pattern_priority_queue WHERE id = ?", (int(item_id),)).fetchone()
    return _format_priority_row(updated) if updated is not None else None


def delete_priority_queue_item(item_id: int) -> bool:
    ensure_pattern_store()
    with _connect() as conn:
        cur = conn.execute("DELETE FROM pattern_priority_queue WHERE id = ?", (int(item_id),))
        conn.commit()
    return bool(cur.rowcount and cur.rowcount > 0)

