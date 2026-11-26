from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from .security import is_architect_authorized
from pydantic import BaseModel, Field

from .config import get_project_root
from . import load_progress
from .db import get_connection, library_connection

router = APIRouter(prefix="/api/skill-review", tags=["Skill Review"])


class FindRequest(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    scientific_field: str = Field(default="", max_length=200)
    limit: int = Field(default=15, ge=1, le=50)
    min_citations: int = Field(default=0, ge=0, le=100000)
    from_year: int | None = Field(default=None, ge=1500, le=2100)
    pubmed_full_text_only: bool = Field(default=False)
    fresh_only: bool = Field(default=False)
    batch_page: int = Field(default=1, ge=1, le=50)
    clear_previous_pending: bool = Field(default=True)


def _root() -> Path:
    root = Path(
        str(
            __import__("os").environ.get("SENTINARI_SHARED_SKILLS_ROOT")
            or __import__("os").environ.get("SMI_SHARED_SKILLS_ROOT")
            or get_project_root() / "data" / "skills"
        )
    ).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _document_chunk_total(document_id: int) -> int:
    try:
        with library_connection("gemma") as conn:
            row = conn.execute("SELECT COUNT(1) AS n FROM chunks WHERE document_id = ?", (document_id,)).fetchone()
        return int(row["n"]) if row is not None else 0
    except Exception:
        return 0


def slugify_text(value: str) -> str:
    """Lightweight slug used only to build a stable placeholder URL."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return slug[:80] or "untitled"


def _pmid_from_url(url: str) -> str:
    m = re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", str(url or ""), re.I)
    return m.group(1) if m else ""


def _source_identity(source_type: str, source_url: str, metadata: dict[str, Any] | None, title: str = "") -> str:
    """Stable identity key for a candidate, so the same dataset arriving
    under different URLs (DOI link vs landing page vs PMC mirror; repo URL
    with/without trailing path; case differences) maps to ONE row.
    """
    metadata = metadata if isinstance(metadata, dict) else {}
    stype = str(source_type or "").strip().lower()
    url = str(source_url or "").strip()

    def _norm_url(u: str) -> str:
        u = str(u or "").strip().lower()
        u = re.sub(r"^[a-z]+://", "", u)
        u = u.split("#", 1)[0].split("?", 1)[0]
        u = u.rstrip("/")
        return u

    if stype == "openalex":
        doi = str(metadata.get("doi") or "").strip().lower()
        if not doi:
            m = re.search(r"doi\.org/(10\.[^/?#]+(?:/[^/?#]+)*)", url, re.I)
            if m:
                doi = m.group(1).strip().lower().rstrip(".")
        if doi:
            return f"doi:{doi}"
        oa_id = str(metadata.get("openalex_id") or "").strip()
        if not oa_id:
            m = re.search(r"openalex\.org/(W\d+)", url, re.I)
            if m:
                oa_id = m.group(1).upper()
        if oa_id:
            return f"openalex:{oa_id.split('/')[-1].upper()}"
        return f"url:{_norm_url(url)}"

    if stype == "pubmed":
        doi = str((metadata or {}).get("doi") or "").strip().lower()
        if not doi:
            m = re.search(r"doi\.org/(10\.[^/?#]+(?:/[^/?#]+)*)", url, re.I)
            if m:
                doi = m.group(1).strip().lower().rstrip(".")
        if doi:
            return f"doi:{doi}"
        m = re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", url, re.I)
        if m:
            return f"pmid:{m.group(1)}"
        pmcid = str((metadata or {}).get("pmcid") or "").strip().upper()
        if pmcid:
            return f"pmc:{pmcid}"
        return f"url:{_norm_url(url)}"

    if stype == "github":
        m = re.search(r"github\.com[/:]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", url, re.I)
        if m:
            owner, repo = m.group(1).lower(), re.sub(r"\.git$", "", m.group(2), flags=re.I).lower()
            return f"github:{owner}/{repo}"
        return f"url:{_norm_url(url)}"

    if stype == "huggingface":
        dataset = url.split("/datasets/")[1] if "/datasets/" in url else str(metadata.get("dataset") or "")
        dataset = dataset.strip("/").lower()
        if dataset:
            return f"hf:{dataset}"
        return f"url:{_norm_url(url)}"

    if stype in {"oecd", "eurostat", "imf", "ecb", "bis", "undata", "bea", "worldbank"}:
        agency = str(metadata.get("agency") or metadata.get("provider") or stype).lower()
        dataset = str(metadata.get("dataset") or metadata.get("indicator") or "").lower()
        if dataset:
            return f"{stype}:{agency}:{dataset}"
        return f"url:{_norm_url(url)}"

    if stype in {"contemporary", "contemporary-journal", "contemporary-article", "contemporary-preprint"}:
        key = _norm_url(url)
        if key and "scholar.google.com" not in key:
            return f"contemporary:{key}"
        return f"contemporary:title:{re.sub(r'[^a-z0-9]+', '-', str(title or '').strip().lower()).strip('-')[:80]}"

    key = _norm_url(url)
    return f"url:{key}" if key else f"title:{str(title or '').strip().lower()}"


_ensured_schema_target: str | None = None


def _schema_target_key() -> str:
    from .db import _get_pg_url

    pg = _get_pg_url()
    return f"pg:{pg}" if pg else f"sqlite:{get_project_root()}"


def _ensure_schema() -> None:
    global _ensured_schema_target
    target = _schema_target_key()
    if _ensured_schema_target == target:
        return
    for _attempt in range(6):
        try:
            _ensure_schema_once()
            _ensured_schema_target = target
            return
        except sqlite3.OperationalError as ex:
            if "locked" not in str(ex).lower() or _attempt == 5:
                raise
            time.sleep(1.5)


def _ensure_schema_once() -> None:
    with get_connection() as conn:
        conn.execute("PRAGMA busy_timeout = 30000;")
        _ensure_schema_body(conn)


def _ensure_schema_body(conn: Any) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS skill_review_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL,
                source_url TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                scientific_field TEXT NOT NULL DEFAULT '',
                target_persona TEXT NOT NULL DEFAULT 'gemma',
                license TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                discovered_at TEXT NOT NULL DEFAULT (datetime('now')),
                reviewed_at TEXT NOT NULL DEFAULT '',
                loaded_document_id INTEGER,
                loaded_title TEXT NOT NULL DEFAULT '',
                loaded_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_skill_review_status
                ON skill_review_candidates(status, discovered_at DESC);
            """
        )
        existing_cols = set()
        try:
            for row in conn.execute("PRAGMA table_info(skill_review_candidates)").fetchall():
                existing_cols.add(str(row["name"]))
        except Exception:
            pass
        for column in ("loaded_document_id INTEGER", "loaded_title TEXT NOT NULL DEFAULT ''", "loaded_at TEXT NOT NULL DEFAULT ''"):
            name = column.split()[0]
            if name not in existing_cols:
                try:
                    conn.execute(f"ALTER TABLE skill_review_candidates ADD COLUMN {column};")
                    conn.commit()
                except Exception:
                    if hasattr(conn, "rollback"):
                        conn.rollback()
        if "identity_key" not in existing_cols:
            try:
                conn.execute("ALTER TABLE skill_review_candidates ADD COLUMN identity_key TEXT NOT NULL DEFAULT '';")
                conn.commit()
            except Exception:
                if hasattr(conn, "rollback"):
                    conn.rollback()
        conn.commit()

        needs_backfill = conn.execute(
            "SELECT COUNT(1) AS n FROM skill_review_candidates WHERE IFNULL(identity_key, '') = ''"
        ).fetchone()[0]
        if int(needs_backfill) > 0:
            rows = conn.execute(
                "SELECT id, source_type, source_url, title, metadata_json FROM skill_review_candidates"
                " WHERE IFNULL(identity_key, '') = ''"
            ).fetchall()
            for row in rows:
                try:
                    meta = json.loads(row["metadata_json"]) if isinstance(row["metadata_json"], str) else dict(row["metadata_json"] or {})
                except Exception:
                    meta = {}
                key = _source_identity(
                    str(row["source_type"] or ""),
                    str(row["source_url"] or ""),
                    meta if isinstance(meta, dict) else {},
                    str(row["title"] or ""),
                )
                conn.execute(
                    "UPDATE skill_review_candidates SET identity_key = ? WHERE id = ?",
                    (key, int(row["id"])),
                )
            conn.commit()

        conn.execute(
            """
            DELETE FROM skill_review_candidates
            WHERE id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY identity_key
                        ORDER BY CASE status WHEN 'approve' THEN 0 WHEN 'test' THEN 1 ELSE 2 END, id
                    ) AS rn
                    FROM skill_review_candidates
                    WHERE IFNULL(identity_key, '') != '' AND status IN ('pending','approve','test')
                ) WHERE rn > 1
            );
            """
        )
        conn.commit()
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_skill_review_identity
                ON skill_review_candidates(identity_key)
                WHERE IFNULL(identity_key, '') != '' AND status IN ('pending','approve','test');
            """
        )
        conn.commit()

        pm_rows = conn.execute(
            "SELECT id, source_type, source_url, metadata_json FROM skill_review_candidates"
            " WHERE source_type = 'pubmed' AND identity_key LIKE 'pmid:%'"
        ).fetchall()
        for pm_row in pm_rows:
            try:
                pm_meta = json.loads(str(pm_row["metadata_json"] or "{}"))
            except Exception:
                pm_meta = {}
            nested = pm_meta.get("_metadata") if isinstance(pm_meta.get("_metadata"), dict) else {}
            doi = str(pm_meta.get("doi") or nested.get("doi") or "").strip().lower()
            upgraded = f"doi:{doi}" if doi else ""
            if upgraded:
                conn.execute(
                    "UPDATE skill_review_candidates SET identity_key = ? WHERE id = ? AND identity_key LIKE 'pmid:%'",
                    (upgraded, int(pm_row["id"])),
                )
        if pm_rows:
            conn.commit()


class DiscoveryRequest(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    scientific_field: str = Field(default="", max_length=200)
    target_persona: str = Field(default="gemma", pattern="^(gemma)$")
    limit: int = Field(default=10, ge=1, le=25)


@router.get("/candidates")
def list_candidates(
    status: str = Query(default="pending"),
    scientific_field: str = Query(default=""),
    query: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
) -> dict[str, Any]:
    """Stored candidates for the review panel, paginated (§76).

    Official scientific & statistical sources (OpenAlex, NLM/PubMed, World Bank,
    Eurostat, IMF, ECB, BIS, UN Data, OECD) sort ahead of GitHub and Hugging Face
    (which are always moved to the last), preserving the current query's
    priority-interleaved insertion order (`id ASC`).
    """
    _ensure_schema()
    from .sentinel_domains import resolve_domain_or_field_filter

    _, field_slugs = resolve_domain_or_field_filter(scientific_field)
    where = "status = ?"
    args: list[Any] = [status.strip() or "pending"]
    if field_slugs:
        placeholders = ",".join("?" for _ in field_slugs)
        where += f" AND REPLACE(LOWER(scientific_field), ' ', '-') IN ({placeholders})"
        args.extend(field_slugs)
    clean_q = str(query or "").strip().lower()
    if clean_q:
        where += " AND (LOWER(metadata_json) LIKE ? OR LOWER(title) LIKE ? OR LOWER(description) LIKE ?)"
        like_q = f"%{clean_q}%"
        args.extend([like_q, like_q, like_q])
    with get_connection() as conn:
        total = int(conn.execute(f"SELECT COUNT(1) AS n FROM skill_review_candidates WHERE {where}", args).fetchone()["n"])
        pages = max(1, (total + page_size - 1) // page_size)
        current = min(max(1, page), pages)
        rows = conn.execute(
            f"""
            SELECT * FROM skill_review_candidates
            WHERE {where}
            ORDER BY CASE
                         WHEN LOWER(source_type) = 'huggingface' THEN 2
                         WHEN LOWER(source_type) = 'github' THEN 1
                         ELSE 0
                     END ASC,
                     id ASC
            LIMIT ? OFFSET ?
            """,
            (*args, page_size, (current - 1) * page_size),
        ).fetchall()
    candidates: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if str(item.get("source_type") or "") == "pubmed":
            try:
                meta = json.loads(str(item.get("metadata_json") or "{}"))
            except Exception:
                meta = {}
            nested = meta.get("_metadata") if isinstance(meta.get("_metadata"), dict) else {}
            for k in ("pmid", "pmcid", "doi"):
                if not item.get(k):
                    item[k] = str(meta.get(k) or nested.get(k) or "")
            item["has_full_text"] = bool(item.get("pmcid"))
        candidates.append(item)
    return {
        "ok": True,
        "candidates": candidates,
        "total": total,
        "page": current,
        "page_size": page_size,
        "pages": pages,
    }


@router.get("/loaded-identities")
def loaded_identities() -> dict[str, Any]:
    """Identity keys of already-loaded datasets — powers the Already-loaded badge."""
    _ensure_schema()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT IFNULL(identity_key, '') AS k FROM skill_review_candidates WHERE status = 'loaded'"
        ).fetchall()
    keys = sorted({str(row["k"]) for row in rows if str(row["k"])})
    return {"ok": True, "identities": keys, "count": len(keys)}


@router.post("/candidates/clear")
def clear_candidates(
    scientific_field: str = Query(default=""),
) -> dict[str, Any]:
    """Remove review-lane candidates so a new science can be searched cleanly.

    Deletes pending / approved / rejected / tested candidates — optionally only
    those of one scientific field or domain. LOADED datasets are never touched:
    they are permanently listed in their field's container.
    """
    _ensure_schema()
    from .sentinel_domains import resolve_domain_or_field_filter

    _, field_slugs = resolve_domain_or_field_filter(scientific_field)
    field = field_slugs[0] if len(field_slugs) == 1 else scientific_field.strip().lower().replace(" ", "-")
    with get_connection() as conn:
        if field_slugs:
            placeholders = ",".join("?" for _ in field_slugs)
            counts = conn.execute(
                f"""
                SELECT status, COUNT(1) AS n FROM skill_review_candidates
                WHERE REPLACE(LOWER(scientific_field), ' ', '-') IN ({placeholders})
                  AND status IN ('pending', 'approve', 'reject', 'test')
                GROUP BY status
                """,
                tuple(field_slugs),
            ).fetchall()
            cur = conn.execute(
                f"""
                DELETE FROM skill_review_candidates
                WHERE REPLACE(LOWER(scientific_field), ' ', '-') IN ({placeholders})
                  AND status IN ('pending', 'approve', 'reject', 'test')
                """,
                tuple(field_slugs),
            )
        else:
            counts = conn.execute(
                """
                SELECT status, COUNT(1) AS n FROM skill_review_candidates
                WHERE status IN ('pending', 'approve', 'reject', 'test')
                GROUP BY status
                """,
            ).fetchall()
            cur = conn.execute(
                """
                DELETE FROM skill_review_candidates
                WHERE status IN ('pending', 'approve', 'reject', 'test')
                """
            )
        conn.commit()
        remaining = conn.execute("SELECT COUNT(1) AS n FROM skill_review_candidates").fetchone()["n"]
    deleted = int(cur.rowcount or 0)
    return {
        "ok": True,
        "deleted": deleted,
        "by_status": {str(row["status"]): int(row["n"]) for row in counts},
        "scientific_field": field,
        "remaining": int(remaining),
    }


@router.get("/loaded")
def list_loaded() -> dict[str, Any]:
    """Permanently listing datasets that were loaded + ingested, per field."""
    _ensure_schema()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, source_type, source_url, title, description,
                   scientific_field, license, loaded_at,
                   loaded_document_id, loaded_title, status
            FROM skill_review_candidates
            WHERE status = 'loaded'
            ORDER BY COALESCE(loaded_at, reviewed_at, discovered_at) DESC
            LIMIT 500
            """
        ).fetchall()
    loaded: list[dict[str, Any]] = []
    chunk_totals: dict[int, int] = {}
    doc_ids = [int(r["loaded_document_id"]) for r in rows if r["loaded_document_id"] is not None]
    direct_docs: list[dict[str, Any]] = []
    try:
        with library_connection("gemma") as conn:
            direct_rows = conn.execute(
                """
                SELECT id, title, source_type, source_path, source_url,
                       scientific_field, created_at, module, topic
                FROM documents
                WHERE module IN ('uploaded-document', 'chat-upload')
                   OR topic = 'sentinel-upload'
                ORDER BY id DESC
                LIMIT 200
                """
            ).fetchall()
            direct_docs = [dict(r) for r in direct_rows]
            for d in direct_docs:
                doc_ids.append(int(d["id"]))
            valid_ids = [d for d in doc_ids if d > 0]
            if valid_ids:
                id_list = ",".join(str(d) for d in set(valid_ids))
                counts = conn.execute(
                    f"SELECT document_id, COUNT(1) AS n FROM chunks WHERE document_id IN ({id_list}) GROUP BY document_id"
                ).fetchall()
                for c in counts:
                    chunk_totals[int(c["document_id"])] = int(c["n"])
    except Exception:
        pass
    seen_doc_ids: set[int] = set()
    for d in direct_docs:
        did = int(d.get("id") or 0)
        if did <= 0 or did in seen_doc_ids:
            continue
        seen_doc_ids.add(did)
        loaded.append(
            {
                "id": 0,
                "source_type": "pdf-upload",
                "source_url": str(d.get("source_url") or ""),
                "title": str(d.get("title") or "Uploaded PDF"),
                "description": f"Uploaded document ({d.get('source_type') or 'pdf'})",
                "scientific_field": str(d.get("scientific_field") or ""),
                "license": "Uploaded",
                "loaded_at": str(d.get("created_at") or ""),
                "loaded_document_id": did,
                "loaded_title": str(d.get("title") or "Uploaded PDF"),
                "status": "loaded",
                "chunk_count": chunk_totals.get(did, 0),
            }
        )
    for row in rows:
        item = dict(row)
        did = int(row["loaded_document_id"] or 0)
        if did > 0:
            seen_doc_ids.add(did)
        item["chunk_count"] = chunk_totals.get(did, 0)
        loaded.append(item)
    return {"ok": True, "loaded": loaded}


def _candidate_document(candidate: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve the knowledge-library document a loaded candidate produced."""
    document_id = int(candidate.get("loaded_document_id") or 0)
    with library_connection("gemma") as conn:
        if document_id > 0:
            row = conn.execute(
                "SELECT id, title, source_type, source_path, source_url, scientific_field, authors, published_date FROM documents WHERE id = ?",
                (document_id,),
            ).fetchone()
            if row is not None:
                return dict(row)
        # Fall back to matching on the stored title within the candidate's field.
        title = str(candidate.get("loaded_title") or candidate.get("title") or "").strip()
        field_slug = str(candidate.get("scientific_field") or "").strip()
        if title:
            row = conn.execute(
                "SELECT id, title, source_type, source_path, source_url, scientific_field, authors, published_date FROM documents WHERE title = ? ORDER BY id DESC LIMIT 1",
                (title,),
            ).fetchone()
            if row is not None:
                return dict(row)
    return None


@router.get("/candidates/{candidate_id}/preview")
def preview_candidate(candidate_id: int) -> dict[str, Any]:
    """HTML-ready preview of a candidate (loaded documents show real text)."""
    _ensure_schema()
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM skill_review_candidates WHERE id = ?", (candidate_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    candidate = dict(row)
    doc = _candidate_document(candidate)
    if doc is not None:
        document_id = int(doc["id"])
        with library_connection("gemma") as conn:
            chunk_rows = conn.execute(
                "SELECT chunk_index, content FROM chunks WHERE document_id = ? ORDER BY chunk_index LIMIT 12",
                (document_id,),
            ).fetchall()
        chunks = [{"index": int(r["chunk_index"]), "text": str(r["content"] or "")[:2400]} for r in chunk_rows]
        total = _document_chunk_total(document_id)
        return {
            "ok": True,
            "ingested": True,
            "document": doc,
            "chunk_total": total,
            "preview_chunks": chunks,
            "truncated": total > len(chunks),
        }
    # Not ingested yet: preview the stored description so review still works.
    return {
        "ok": True,
        "ingested": False,
        "document": {
            "title": candidate.get("title"),
            "source_type": candidate.get("source_type"),
            "source_url": candidate.get("source_url"),
            "scientific_field": candidate.get("scientific_field"),
        },
        "preview_chunks": [{"index": 0, "text": str(candidate.get("description") or "No description stored.")[:2400]}],
        "chunk_total": 0,
        "truncated": False,
        "note": "Not ingested yet — this is the discovery description. Load the dataset to preview its full text.",
    }


@router.get("/candidates/{candidate_id}/download")
def download_candidate(candidate_id: int, request: Request):
    """Download a candidate's stored artifact as .pdf (real PDF when we have one)."""
    if not is_architect_authorized(request):
        raise HTTPException(
            status_code=403,
            detail="Direct candidate dataset download is restricted to the Chief Architect (Dr. Pierre C. Wepener). Please read this dataset online via the in-system Sovereign E-Book reader.",
        )
    _ensure_schema()
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM skill_review_candidates WHERE id = ?", (candidate_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    candidate = dict(row)
    doc = _candidate_document(candidate)
    if doc is None:
        raise HTTPException(status_code=409, detail="This dataset has not been loaded yet. Load it first — download works after ingestion.")
    document_id = int(doc["id"])
    source_path = Path(str(doc.get("source_path") or ""))
    if source_path.suffix.lower() == ".pdf" and source_path.exists():
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(doc.get("title") or source_path.name))[:80] or "dataset"
        return FileResponse(path=str(source_path), media_type="application/pdf", filename=f"{safe_name}.pdf")
    with library_connection("gemma") as conn:
        rows = conn.execute(
            "SELECT content FROM chunks WHERE document_id = ? ORDER BY chunk_index",
            (document_id,),
        ).fetchall()
    text = "\n\n".join(str(r["content"] or "") for r in rows).strip()
    if not text:
        raise HTTPException(status_code=404, detail="No ingested text available to build a PDF.")
    from .text_pdf import text_to_pdf_response

    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(doc.get("title") or "dataset"))[:80] or "dataset"
    return text_to_pdf_response(text, filename=f"{safe_name}.pdf", title=str(doc.get("title") or "SMi Sentinel Dataset"))


@router.get("/documents/{document_id}/preview")
def preview_document(
    document_id: int,
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=12, ge=1, le=100),
    all_chunks: int = Query(default=0),
) -> dict[str, Any]:
    """HTML / E-Book preview of a loaded dataset: text chunks rendered for the in-system reader."""
    from html import escape

    with library_connection("gemma") as conn:
        doc = conn.execute(
            "SELECT id, title, source_type, source_path, source_url, scientific_field, authors, published_date FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found in the knowledge library.")
        
        total_chunks = _document_chunk_total(document_id)
        if all_chunks:
            chunk_rows = conn.execute(
                "SELECT chunk_index, content FROM chunks WHERE document_id = ? ORDER BY chunk_index",
                (document_id,),
            ).fetchall()
        else:
            offset = max(0, (page - 1) * page_size)
            chunk_rows = conn.execute(
                "SELECT chunk_index, content FROM chunks WHERE document_id = ? ORDER BY chunk_index LIMIT ? OFFSET ?",
                (document_id, page_size, offset),
            ).fetchall()

    chunks = [
        {
            "index": int(row["chunk_index"]),
            "text": str(row["content"] or "")[:4000],
        }
        for row in chunk_rows
    ]
    is_admin = is_architect_authorized(request)
    return {
        "ok": True,
        "is_admin": is_admin,
        "document": {
            "id": int(doc["id"]),
            "title": str(doc["title"] or "Untitled"),
            "source_type": str(doc["source_type"] or ""),
            "source_path": str(doc["source_path"] or ""),
            "source_url": str(doc["source_url"] or ""),
            "scientific_field": str(doc["scientific_field"] or ""),
            "authors": str(doc["authors"] or ""),
            "published_date": str(doc["published_date"] or ""),
        },
        "chunk_total": total_chunks,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total_chunks + page_size - 1) // page_size) if total_chunks else 1,
        "preview_chunks": chunks,
        "all_chunks_loaded": bool(all_chunks) or len(chunks) >= total_chunks,
        "truncated": total_chunks > len(chunks) and not all_chunks,
    }


@router.get("/documents/{document_id}/download")
def download_document(document_id: int, request: Request):
    """Download the stored dataset artifact as a real .pdf when available."""
    if not is_architect_authorized(request):
        raise HTTPException(
            status_code=403,
            detail="Direct document PDF download is restricted to the Chief Architect (Dr. Pierre C. Wepener). Please read this dataset online via the in-system Sovereign E-Book reader.",
        )
    with library_connection("gemma") as conn:
        doc = conn.execute(
            "SELECT title, source_path, source_type FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found in the knowledge library.")
    source_path = Path(str(doc["source_path"] or ""))
    if source_path.suffix.lower() == ".pdf" and source_path.exists():
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(doc["title"] or source_path.name))[:80] or "dataset"
        return FileResponse(
            path=str(source_path),
            media_type="application/pdf",
            filename=f"{safe_name}.pdf",
        )
    # Non-PDF artifacts: convert the ingested text to a generated PDF.
    from .text_pdf import text_to_pdf_response

    with library_connection("gemma") as conn:
        rows = conn.execute(
            "SELECT content FROM chunks WHERE document_id = ? ORDER BY chunk_index",
            (document_id,),
        ).fetchall()
    text = "\n\n".join(str(row["content"] or "") for row in rows).strip()
    if not text:
        raise HTTPException(status_code=404, detail="No ingested text available to build a PDF.")
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(doc["title"] or "dataset"))[:80] or "dataset"
    return text_to_pdf_response(text, filename=f"{safe_name}.pdf")


@router.post("/discover")
def discover_candidates(payload: DiscoveryRequest) -> dict[str, Any]:
    _ensure_schema()
    from .sentinel_domains import sanitize_field_and_domain

    canon_field, canon_domain = sanitize_field_and_domain(
        payload.scientific_field, fallback_text=payload.query
    )
    field_to_store = canon_field or payload.scientific_field.strip()
    headers = {"User-Agent": "SMI-Skill-Review/1.0"}
    candidates: list[dict[str, Any]] = []

    hf = requests.get(
        "https://huggingface.co/api/datasets",
        params={"search": payload.query, "limit": payload.limit},
        headers=headers,
        timeout=30,
    )
    hf.raise_for_status()
    hf_items = hf.json()
    for item in hf_items if isinstance(hf_items, list) else []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        candidates.append(
            {
                "source_type": "huggingface",
                "source_url": f"https://huggingface.co/datasets/{item['id']}",
                "title": str(item["id"]),
                "description": str(item.get("description") or "")[:1000],
                "scientific_field": field_to_store,
                "domain_slug": canon_domain,
                "target_persona": payload.target_persona,
                "license": "",
            }
        )

    github = requests.get(
        "https://api.github.com/search/repositories",
        params={"q": f"{payload.query} in:name,description", "per_page": payload.limit},
        headers=headers,
        timeout=30,
    )
    github.raise_for_status()
    github_items = github.json().get("items", []) if isinstance(github.json(), dict) else []
    for item in github_items:
        if not isinstance(item, dict) or not item.get("html_url"):
            continue
        license_data = item.get("license")
        candidates.append(
            {
                "source_type": "github",
                "source_url": str(item["html_url"]),
                "title": str(item.get("full_name") or item.get("name") or "Repository"),
                "description": str(item.get("description") or "")[:1000],
                "scientific_field": field_to_store,
                "domain_slug": canon_domain,
                "target_persona": payload.target_persona,
                "license": str(license_data.get("spdx_id") or "") if isinstance(license_data, dict) else "",
            }
        )

    with get_connection() as conn:
        duplicates = 0
        for item in candidates:
            identity = _source_identity(
                str(item.get("source_type") or ""),
                str(item.get("source_url") or ""),
                item,
                str(item.get("title") or ""),
            )
            already = conn.execute(
                "SELECT status FROM skill_review_candidates WHERE identity_key = ?",
                (identity,),
            ).fetchone() if identity else None
            if already is not None and str(already["status"]) in ("loaded", "reject"):
                # Owner directive (§34): loaded datasets must never re-enter
                # the review lineup through any write lane.
                duplicates += 1
                continue
            try:
                conn.execute(
                    """
                    INSERT INTO skill_review_candidates
                        (source_type, source_url, title, description, scientific_field,
                         target_persona, license, metadata_json, identity_key, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                    ON CONFLICT(identity_key) WHERE IFNULL(identity_key, '') != ''
                         AND status IN ('pending','approve','test')
                    DO UPDATE SET
                        description = excluded.description,
                        scientific_field = excluded.scientific_field,
                        target_persona = excluded.target_persona,
                        license = excluded.license
                    """,
                    (
                        item["source_type"],
                        item["source_url"],
                        item["title"],
                        item["description"],
                        item["scientific_field"],
                        item["target_persona"],
                        item["license"],
                        json.dumps({"query": payload.query}, ensure_ascii=True),
                        identity,
                    ),
                )
            except sqlite3.IntegrityError:
                duplicates += 1
        conn.commit()
    return {"ok": True, "discovered": len(candidates), "duplicates_skipped": duplicates, "review_required": True}


def _novelty_rank(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Owner directive (§35): rank candidates by novelty against the whole
    library — most-cited first, recency breaking ties, open access / PMC
    full text as a light bonus. Candidates arriving here are already free
    of loaded / rejected / duplicate identities (the §34 sweep), so what
    remains IS the fresh set; this orders it for discovery value."""
    from datetime import datetime, timezone

    try:
        current_year = datetime.now(timezone.utc).year
    except Exception:
        current_year = 2026

    def _score(c: dict[str, Any]) -> float:
        try:
            citations = int(c.get("cited_by_count") or 0)
        except Exception:
            citations = 0
        year = 0
        for key in ("year", "publication_year"):
            try:
                if c.get(key):
                    year = int(c[key])
                    break
            except Exception:
                pass
        # The §22 window (last ~7 years) earns a full recency bonus ordered
        # newest-first; older works decay to a floor of zero.
        recency = max(0, (year - (current_year - 7)) * 5) if year else 0
        oa_bonus = 2.0 if (c.get("is_oa") or c.get("has_full_text")) else 0.0
        return float(citations) + float(recency) + oa_bonus

    return sorted(candidates, key=_score, reverse=True)


# ---------------------------------------------------------------------------
# §74n — Whole-string precision law (owner directive).
#
# A sourcing search must honor the ENTIRE search string. Before this law the
# lanes broadened freely: "Linux Ubuntu LTS for Beginners" came back drowned
# in field-wide noise ("everything from the Ubuntu Culture and whatever")
# because providers do token-OR matching and the OpenAlex lane re-sorted by
# citation count, floating field heavyweights above topical matches.
#
# Every source lane flows through the single chokepoint in ``find_candidates``
# below, where candidates that do not carry the whole string are dropped —
# narrowed, never broadened.
# ---------------------------------------------------------------------------
_PHRASE_STOPWORDS = frozenset(
    {"for", "the", "and", "of", "a", "an", "to", "in", "with", "on", "by", "at", "from"}
)


def _precision_terms(query: str) -> list[str]:
    """Content words of the search string (stopwords dropped for matching)."""
    tokens = re.findall(r"[a-z0-9]+", str(query or "").lower())
    content = [t for t in tokens if t not in _PHRASE_STOPWORDS]
    return content or tokens


def _normalize_for_match(text: str) -> str:
    """Lowercase, drop punctuation/stopwords, collapse whitespace — so
    'linux-ubuntu-LTS for beginners' and 'Linux Ubuntu LTS for Beginners'
    compare equal."""
    tokens = re.findall(r"[a-z0-9]+", str(text or "").lower())
    return " ".join(t for t in tokens if t not in _PHRASE_STOPWORDS)


def _precision_score(candidate: dict[str, Any], terms: list[str], phrase: str) -> tuple[int, int]:
    """Return (tier, hits) against title + description + abstract.

    Tier 0 = the entire phrase present in order (slug forms count — dashes
    normalize away). Tier 1 = every content word present. Tier 2 = all but
    one. Anything weaker is field-level dilution and gets dropped.
    """
    haystack = _normalize_for_match(
        f"{candidate.get('title') or ''} {candidate.get('description') or ''} {candidate.get('abstract') or ''}"
    )
    hits = sum(1 for t in terms if t in haystack)
    if phrase and phrase in haystack:
        return 0, hits
    if terms and hits >= len(terms):
        return 1, hits
    if terms and hits >= max(1, len(terms) - 1):
        return 2, hits
    return 3, hits


@router.post("/find")
def find_candidates(payload: FindRequest) -> dict[str, Any]:
    """Search OpenAlex, NLM/PubMed, World Bank, Eurostat, IMF, ECB, BIS, UN Data,
    OECD, GitHub, and Hugging Face at the same time.

    Official scientific & statistical sources are interleaved at the front so
    OpenAlex, NLM/NHLBI/PubMed, World Bank, Eurostat, IMF, ECB, BIS, UN Data,
    and OECD appear right on Page 1, while GitHub and Hugging Face are moved
    to the very last.
    """
    _ensure_schema()
    from .sentinel_domains import sanitize_field_and_domain

    headers = {"User-Agent": "SMI-Skill-Review/1.0"}
    query = payload.query.strip()
    batch_page = max(1, int(payload.batch_page or 1))
    canon_field, canon_domain = sanitize_field_and_domain(payload.scientific_field, fallback_text=query)
    field_text = canon_field or payload.scientific_field.strip()

    def _github_search() -> list[dict[str, Any]]:
        try:
            resp = requests.get(
                "https://api.github.com/search/repositories",
                params={
                    "q": f"{query} in:name,description",
                    "per_page": payload.limit,
                    "page": batch_page,
                    "sort": "best-match",
                },
                headers=headers,
                timeout=20,
            )
            if resp.status_code != 200:
                return []
            items = resp.json().get("items", []) if isinstance(resp.json(), dict) else []
            out: list[dict[str, Any]] = []
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict) or not item.get("html_url"):
                    continue
                license_data = item.get("license")
                out.append(
                    {
                        "source_type": "github",
                        "source_url": str(item["html_url"]),
                        "title": str(item.get("full_name") or item.get("name") or "Repository"),
                        "description": str(item.get("description") or "")[:1000],
                        "scientific_field": field_text,
                        "target_persona": "gemma",
                        "license": str(license_data.get("spdx_id") or "") if isinstance(license_data, dict) else "",
                        "stars": int(item.get("stargazers_count") or 0),
                        "search_query": query.lower(),
                    }
                )
            return out
        except Exception:
            return []

    def _huggingface_search() -> list[dict[str, Any]]:
        try:
            fetch_n = min(100, payload.limit * batch_page)
            resp = requests.get(
                "https://huggingface.co/api/datasets",
                params={"search": query, "limit": fetch_n, "full": "false"},
                headers=headers,
                timeout=20,
            )
            if resp.status_code != 200:
                return []
            items = resp.json()
            if not isinstance(items, list):
                return []
            start_idx = (batch_page - 1) * payload.limit
            sliced = items[start_idx : start_idx + payload.limit]
            out = []
            for item in sliced:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                out.append(
                    {
                        "source_type": "huggingface",
                        "source_url": f"https://huggingface.co/datasets/{item['id']}",
                        "title": str(item["id"]),
                        "description": str(item.get("description") or item.get("cardData", {}).get("pretty_name") or "")[:1000],
                        "scientific_field": field_text,
                        "target_persona": "gemma",
                        "license": "",
                        "downloads": int(item.get("downloads") or 0),
                        "search_query": query.lower(),
                    }
                )
            return out
        except Exception:
            return []

    def _openalex_search() -> list[dict[str, Any]]:
        try:
            from .openalex_worker import search_openalex_works

            result = search_openalex_works(
                query,
                field=field_text,
                limit=min(25, payload.limit * batch_page),
                min_citations=payload.min_citations,
                from_year=payload.from_year,
            )
            cands = list(result.get("candidates") or [])
            if batch_page > 1 and len(cands) > payload.limit:
                cands = cands[(batch_page - 1) * max(1, payload.limit // 2) :]
            for c in cands:
                c["search_query"] = query.lower()
            return cands
        except Exception:
            return []

    eu_data_portal_error: str | None = None

    def _eu_data_portal_search() -> list[dict[str, Any]]:
        nonlocal eu_data_portal_error
        try:
            from .eu_portal_search import search_eu_datasets

            result = search_eu_datasets(
                query,
                page=batch_page - 1,
                limit=min(50, payload.limit),
                from_year=payload.from_year,
            )
            candidates = []
            for dataset in result.get("datasets") or []:
                details = [
                    str(dataset.get("description") or "").strip(),
                    f"Publisher: {dataset.get('publisher')}" if dataset.get("publisher") else "",
                    f"Catalogue: {dataset.get('catalogue')}" if dataset.get("catalogue") else "",
                    f"Issued: {dataset.get('issued')}" if dataset.get("issued") else "",
                ]
                candidates.append(
                    {
                        "source_type": "eu_data_portal",
                        "source_url": str(dataset.get("source_url") or ""),
                        "title": str(dataset.get("title") or "Untitled EU dataset")[:500],
                        "description": " · ".join(part for part in details if part)[:3000],
                        "scientific_field": field_text,
                        "target_persona": "gemma",
                        "license": str(dataset.get("license") or ""),
                        "authors": [str(dataset.get("publisher") or "European Data Portal")],
                        "dataset_id": str(dataset.get("dataset_id") or ""),
                        "publisher": str(dataset.get("publisher") or ""),
                        "catalogue": str(dataset.get("catalogue") or ""),
                        "issued": str(dataset.get("issued") or ""),
                        "modified": str(dataset.get("modified") or ""),
                        "distributions": dataset.get("distributions") or [],
                        "search_query": query.lower(),
                    }
                )
            return candidates
        except Exception as exc:
            eu_data_portal_error = str(exc)[:200] or "European Data Portal search failed."
            return []

    def _pubmed_search() -> list[dict[str, Any]]:
        try:
            from .pubmed_worker import search_pubmed_papers

            result = search_pubmed_papers(
                query,
                field=field_text,
                limit=min(25, payload.limit * batch_page),
                from_year=payload.from_year,
                full_text_only=bool(payload.pubmed_full_text_only),
            )
            if not result.get("ok"):
                return []
            cands = list(result.get("candidates") or [])
            if batch_page > 1 and len(cands) > payload.limit:
                cands = cands[(batch_page - 1) * max(1, payload.limit // 2) :]
            for c in cands:
                c["search_query"] = query.lower()
            return cands
        except Exception:
            return []

    def _worldbank_search() -> list[dict[str, Any]]:
        try:
            from .worldbank_worker import search_dbnomics_datasets

            result = search_dbnomics_datasets(query, field=field_text, limit=max(4, min(15, payload.limit)))
            cands = list(result.get("candidates") or [])
            for c in cands:
                c["search_query"] = query.lower()
            return cands
        except Exception:
            return []

    def _oecd_search() -> list[dict[str, Any]]:
        try:
            from .oecd_worker import search_oecd_datasets

            result = search_oecd_datasets(query, field=field_text, limit=max(3, min(10, payload.limit)))
            cands = list(result.get("candidates") or [])
            for c in cands:
                c["search_query"] = query.lower()
            return cands
        except Exception:
            return []

    def _intl_stat_search(provider_key: str) -> list[dict[str, Any]]:
        try:
            from .intl_stats_worker import search_intl_stat_provider

            result = search_intl_stat_provider(
                provider_key,
                query,
                field=field_text,
                limit=max(3, min(8, payload.limit)),
                page=batch_page,
            )
            cands = list(result.get("candidates") or [])
            for c in cands:
                c["search_query"] = query.lower()
            return cands
        except Exception:
            return []

    def _contemporary_search() -> list[dict[str, Any]]:
        try:
            from .contemporary_scraper import search_contemporary_candidates

            result = search_contemporary_candidates(
                query,
                field=field_text,
                limit=max(4, min(10, payload.limit)),
                page=batch_page,
            )
            cands = list(result.get("candidates") or [])
            for c in cands:
                c["search_query"] = query.lower()
            return cands
        except Exception:
            return []

    import time as _search_time

    _search_deadline = _search_time.monotonic() + 55.0

    def _lane_result(future: Any) -> list[dict[str, Any]]:
        remaining = _search_deadline - _search_time.monotonic()
        try:
            return list(future.result(timeout=max(1.0, remaining)) or [])
        except Exception:
            return []

    pool = ThreadPoolExecutor(max_workers=14)
    try:
        openalex_future = pool.submit(_openalex_search)
        eu_data_portal_future = pool.submit(_eu_data_portal_search)
        pubmed_future = pool.submit(_pubmed_search)
        worldbank_future = pool.submit(_worldbank_search)
        eurostat_future = pool.submit(_intl_stat_search, "eurostat")
        imf_future = pool.submit(_intl_stat_search, "imf")
        ecb_future = pool.submit(_intl_stat_search, "ecb")
        bis_future = pool.submit(_intl_stat_search, "bis")
        undata_future = pool.submit(_intl_stat_search, "undata")
        bea_future = pool.submit(_intl_stat_search, "bea")
        oecd_future = pool.submit(_oecd_search)
        contemp_future = pool.submit(_contemporary_search)
        github_future = pool.submit(_github_search)
        hf_future = pool.submit(_huggingface_search)
        candidates = [
            *_lane_result(openalex_future),
            *_lane_result(eu_data_portal_future),
            *_lane_result(pubmed_future),
            *_lane_result(worldbank_future),
            *_lane_result(eurostat_future),
            *_lane_result(imf_future),
            *_lane_result(ecb_future),
            *_lane_result(bis_future),
            *_lane_result(undata_future),
            *_lane_result(bea_future),
            *_lane_result(oecd_future),
            *_lane_result(contemp_future),
            *_lane_result(github_future),
            *_lane_result(hf_future),
        ]
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    try:
        from .pattern_store import rejected_identities as _rejected_identities

        _rejected = set(_rejected_identities())
    except Exception:
        _rejected = set()

    for item in candidates:
        extra = item.get("_metadata") if isinstance(item.get("_metadata"), dict) else {}
        for k in ("pmid", "pmcid", "doi"):
            if extra.get(k) and not item.get(k):
                item[k] = str(extra[k])
        item.pop("_metadata", None)
        item["search_query"] = query.lower()
        source_url = str(item.get("source_url") or "").strip()
        if not source_url and str(item.get("source_type") or "") == "openalex":
            source_url = str(
                item.get("landing_page_url")
                or (f"https://doi.org/{item['doi']}" if item.get("doi") else "")
                or item.get("openalex_id")
                or f"openalex:{slugify_text(item.get('title') or 'work')}"
            ).strip()
            item["source_url"] = source_url
        item.setdefault("source_url", source_url)
        item["_identity"] = _source_identity(
            str(item.get("source_type") or ""),
            str(item.get("source_url") or ""),
            item if isinstance(item, dict) else {},
            str(item.get("title") or ""),
        )

    unique_candidates: list[dict[str, Any]] = []
    seen_identities: set[str] = set()
    duplicate_count = 0
    for item in candidates:
        identity = str(item.get("_identity") or "")
        if identity and identity in seen_identities:
            duplicate_count += 1
            continue
        if identity and identity in _rejected:
            duplicate_count += 1
            continue
        if identity:
            seen_identities.add(identity)
        unique_candidates.append(item)

    # Whole-string precision gate BEFORE DB insertion so dropped imprecise
    # candidates never pollute skill_review_candidates.
    # Official statistical catalogues, NLM/PubMed E-utilities matches, and
    # Scraped Contemporary Sources are already scoped by their upstream search
    # engines and kept intact.
    _EXEMPT_SOURCES = {"eu_data_portal", "worldbank", "oecd", "eurostat", "imf", "ecb", "bis", "undata", "bea", "pubmed", "contemporary"}
    terms = _precision_terms(query)
    phrase = _normalize_for_match(query)
    scored: list[dict[str, Any]] = []
    precision_dropped = 0
    for item in unique_candidates:
        st_low = str(item.get("source_type") or "").lower()
        if st_low in _EXEMPT_SOURCES:
            item["_precision_tier"] = 0
            item["_precision_hits"] = len(terms)
            scored.append(item)
            continue
        tier, hits = _precision_score(item, terms, phrase)
        item["_precision_tier"] = tier
        item["_precision_hits"] = hits
        if hits >= len(terms) - (0 if len(terms) <= 2 else 1):
            scored.append(item)
        else:
            precision_dropped += 1

    if payload.fresh_only:
        ranked: list[dict[str, Any]] = []
        for tier in sorted({int(c.get("_precision_tier") or 0) for c in scored}):
            ranked.extend(_novelty_rank([c for c in scored if int(c.get("_precision_tier") or 0) == tier]))
        scored = ranked
    else:
        scored.sort(key=lambda c: int(c.get("_precision_tier") or 0))

    # Interleave primary scientific, official statistical, and Scraped
    # Contemporary Sources at the front so Page 1 shows OpenAlex, NLM/PubMed,
    # World Bank, Eurostat, IMF, ECB, BIS, UN Data, BEA, OECD, and Scraped
    # Contemporary Sources together, while moving all GitHub and Hugging Face
    # results to the very last!
    by_source: dict[str, list[dict[str, Any]]] = {}
    for c in scored:
        st_low = str(c.get("source_type") or "").lower()
        by_source.setdefault(st_low, []).append(c)

    primary_quotas = [
        ("openalex", 3),
        ("eu_data_portal", 2),
        ("pubmed", 2),
        ("worldbank", 2),
        ("eurostat", 2),
        ("imf", 2),
        ("ecb", 2),
        ("bis", 2),
        ("undata", 2),
        ("bea", 2),
        ("oecd", 2),
        ("contemporary", 4),
    ]
    interleaved_primary: list[dict[str, Any]] = []
    while any(by_source.get(st) for st, _q in primary_quotas):
        for st, quota in primary_quotas:
            bucket = by_source.get(st) or []
            for _ in range(quota):
                if bucket:
                    interleaved_primary.append(bucket.pop(0))

    tail_sources = [
        *(by_source.get("github") or []),
        *(by_source.get("huggingface") or []),
    ]
    ordered_candidates = [*interleaved_primary, *tail_sources]

    loaded_skipped = 0
    final_candidates: list[dict[str, Any]] = []
    with get_connection() as conn:
        # When starting a new discovery query (batch_page == 1), clear stale
        # un-reviewed `pending` candidates from previous queries so pagination
        # only flows through the current query's candidate pool.
        if payload.clear_previous_pending and batch_page == 1:
            conn.execute("DELETE FROM skill_review_candidates WHERE status = 'pending'")

        _known_rejected = _rejected | {
            str(r["identity_key"])
            for r in conn.execute(
                "SELECT identity_key FROM skill_review_candidates WHERE status = 'reject' AND identity_key IS NOT NULL AND identity_key != ''"
            ).fetchall()
        }

        all_identities = [str(c.get("_identity") or "") for c in ordered_candidates if c.get("_identity")]
        existing_by_identity: dict[str, dict[str, Any]] = {}
        if all_identities:
            marks_id = ",".join("?" for _ in all_identities)
            for r in conn.execute(
                f"SELECT id, identity_key, status FROM skill_review_candidates WHERE identity_key IN ({marks_id})",
                all_identities,
            ).fetchall():
                existing_by_identity[str(r["identity_key"])] = dict(r)

        all_urls = [str(c.get("source_url") or "") for c in ordered_candidates if c.get("source_url")]
        existing_by_url: dict[str, dict[str, Any]] = {}
        if all_urls:
            marks_url = ",".join("?" for _ in all_urls)
            for r in conn.execute(
                f"SELECT id, source_url, status FROM skill_review_candidates WHERE source_url IN ({marks_url})",
                all_urls,
            ).fetchall():
                existing_by_url[str(r["source_url"])] = dict(r)

        for item in ordered_candidates:
            item.pop("_precision_tier", None)
            item.pop("_precision_hits", None)
            identity = str(item.get("_identity") or "")
            if identity and identity in _known_rejected:
                duplicate_count += 1
                continue
            item_field, item_domain = sanitize_field_and_domain(
                str(item.get("field_slug") or item.get("scientific_field") or field_text),
                fallback_text=f"{query} {item.get('title') or ''} {item.get('description') or item.get('abstract') or ''}",
            )
            eff_field = item_field or field_text or "physics"
            item["scientific_field"] = eff_field
            item["field_slug"] = eff_field
            if item_domain:
                item["domain_slug"] = item_domain
            existing = existing_by_identity.get(identity) if identity else None
            if existing is not None:
                st_val = str(existing["status"])
                if st_val == "loaded":
                    loaded_skipped += 1
                    continue
                if st_val == "reject":
                    duplicate_count += 1
                    continue
                item["id"] = int(existing["id"])
                item["already_loaded"] = False
                item["previously_rejected"] = False
                conn.execute(
                    "UPDATE skill_review_candidates SET description = ?, scientific_field = ?, license = ?, metadata_json = ?, discovered_at = datetime('now') WHERE id = ?",
                    (
                        str(item.get("description") or item.get("abstract") or "")[:1000],
                        eff_field,
                        str(item.get("license") or ""),
                        json.dumps(item, ensure_ascii=True)[:6000],
                        int(existing["id"]),
                    ),
                )
                final_candidates.append(item)
                continue
            try:
                s_url = str(item.get("source_url") or "")
                url_existing = existing_by_url.get(s_url) if s_url else None
                if url_existing is not None:
                    if str(url_existing["status"]) == "loaded":
                        loaded_skipped += 1
                        continue
                    if str(url_existing["status"]) == "reject":
                        duplicate_count += 1
                        continue
                    conn.execute("DELETE FROM skill_review_candidates WHERE id = ?", (int(url_existing["id"]),))
                cur = conn.execute(
                    """
                    INSERT INTO skill_review_candidates
                        (source_type, source_url, title, description, scientific_field,
                         target_persona, license, metadata_json, identity_key, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        str(item.get("source_type") or "github"),
                        s_url,
                        str(item.get("title") or "Untitled candidate"),
                        str(item.get("description") or item.get("abstract") or "")[:1000],
                        eff_field,
                        "gemma",
                        str(item.get("license") or ""),
                        json.dumps(item, ensure_ascii=True)[:6000],
                        identity,
                    ),
                )
                item["id"] = int(cur.lastrowid or 0)
                item["already_loaded"] = False
                item["previously_rejected"] = False
                final_candidates.append(item)
            except Exception:
                duplicate_count += 1
        conn.commit()
    candidates = final_candidates

    return {
        "ok": True,
        "query": query,
        "field": field_text,
        "batch_page": batch_page,
        "fresh_only": bool(payload.fresh_only),
        "count": len(candidates),
        "duplicates_skipped": duplicate_count,
        "loaded_skipped": loaded_skipped,
        "precision": {
            "mode": "whole-string",
            "terms": terms,
            "kept": len(candidates),
            "dropped_imprecise": precision_dropped,
            "note": (
                ""
                if candidates
                else "No candidate carried the entire search string — precision kept nothing rather than diluting into the field."
            ),
        },
        "openalex_count": sum(1 for c in candidates if c["source_type"] == "openalex"),
        "eu_data_portal_count": sum(1 for c in candidates if c["source_type"] == "eu_data_portal"),
        "eu_data_portal_error": eu_data_portal_error,
        "pubmed_count": sum(1 for c in candidates if c["source_type"] == "pubmed"),
        "worldbank_count": sum(1 for c in candidates if c["source_type"] == "worldbank"),
        "eurostat_count": sum(1 for c in candidates if c["source_type"] == "eurostat"),
        "imf_count": sum(1 for c in candidates if c["source_type"] == "imf"),
        "ecb_count": sum(1 for c in candidates if c["source_type"] == "ecb"),
        "bis_count": sum(1 for c in candidates if c["source_type"] == "bis"),
        "undata_count": sum(1 for c in candidates if c["source_type"] == "undata"),
        "bea_count": sum(1 for c in candidates if c["source_type"] == "bea"),
        "oecd_count": sum(1 for c in candidates if c["source_type"] == "oecd"),
        "contemporary_count": sum(1 for c in candidates if c["source_type"] == "contemporary"),
        "github_count": sum(1 for c in candidates if c["source_type"] == "github"),
        "huggingface_count": sum(1 for c in candidates if c["source_type"] == "huggingface"),
        "pubmed_fulltext_count": sum(
            1 for c in candidates
            if c.get("source_type") == "pubmed" and (c.get("has_full_text") or str(c.get("pmcid") or ""))
        ),
        "candidates": candidates,
        "review_required": True,
    }


@router.post("/candidates/save")
def save_candidates(payload: dict[str, Any]) -> dict[str, Any]:
    """Store review-picked OpenAlex works (or HF/GitHub datasets) as candidates."""
    _ensure_schema()
    from .sentinel_domains import sanitize_field_and_domain

    items = payload.get("candidates")
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="Provide a candidates list to store.")
    raw_field = str(payload.get("scientific_field") or "").strip()
    saved = 0
    duplicates = 0
    with get_connection() as conn:
        for item in items:
            if not isinstance(item, dict):
                continue
            source_url = str(item.get("source_url") or item.get("openalex_id") or item.get("landing_page_url") or "").strip()
            if not source_url:
                continue
            title = str(item.get("title") or "Untitled candidate")
            desc = str(item.get("abstract") or item.get("description") or "")[:1000]
            canon_field, canon_domain = sanitize_field_and_domain(
                str(item.get("field_slug") or item.get("scientific_field") or raw_field),
                fallback_text=f"{title} {desc}",
            )
            eff_field = canon_field or raw_field or "physics"
            item["scientific_field"] = eff_field
            item["field_slug"] = eff_field
            if canon_domain:
                item["domain_slug"] = canon_domain
            identity = _source_identity(
                str(item.get("source_type") or "openalex"),
                source_url,
                item if isinstance(item, dict) else {},
                title,
            )
            already = conn.execute(
                "SELECT status FROM skill_review_candidates WHERE identity_key = ?",
                (identity,),
            ).fetchone() if identity else None
            if already is not None and str(already["status"]) in ("loaded", "reject"):
                # Owner directive (§34): loaded datasets must never re-enter
                # the review lineup through any write lane.
                duplicates += 1
                continue
            try:
                conn.execute(
                    """
                    INSERT INTO skill_review_candidates
                        (source_type, source_url, title, description, scientific_field,
                         target_persona, license, metadata_json, identity_key, status)
                    VALUES (?, ?, ?, ?, ?, 'gemma', ?, ?, ?, 'pending')
                    ON CONFLICT(identity_key) WHERE IFNULL(identity_key, '') != ''
                         AND status IN ('pending','approve','test')
                    DO UPDATE SET
                        description = excluded.description,
                        scientific_field = excluded.scientific_field
                    """,
                    (
                        str(item.get("source_type") or "openalex"),
                        source_url,
                        title,
                        desc,
                        eff_field,
                        str(item.get("license") or ""),
                        json.dumps(item, ensure_ascii=True)[:4000],
                        identity,
                    ),
                )
            except sqlite3.IntegrityError:
                duplicates += 1
                continue
            saved += 1
        conn.commit()
    return {"ok": True, "saved": saved, "duplicates_skipped": duplicates, "review_required": True}


@router.post("/candidates/{candidate_id}/ingest")
def ingest_candidate(candidate_id: int, wait: int = Query(default=0, ge=0, le=1)) -> dict[str, Any]:
    """Download + digest a stored candidate into its scientific field.

    Works for any source_type: OpenAlex works (PDF/landing-page/record),
    GitHub repos, and Hugging Face datasets. Works straight from the stored
    candidate row — no client-side save/re-lookup dance is needed.
    """
    from .openalex_worker import load_openalex_works_into_field
    from .sentinel_domains import ingest_github_dataset_to_field, ingest_huggingface_dataset_to_field

    _ensure_schema()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM skill_review_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    candidate = dict(row)

    if not wait:
        # Owner directive: loads run through the sequential background queue —
        # one at a time, never overlapping, each with live per-job progress.
        from .load_queue import get_load_queue

        try:
            entry = get_load_queue().enqueue(candidate)
        except ValueError as ex:
            raise HTTPException(status_code=409, detail=str(ex))
        return {
            "ok": True,
            "queued": True,
            "async": True,
            "entry_id": entry.get("entry_id"),
            "position": entry.get("position"),
            "already_queued": bool(entry.get("already_queued")),
        }
    return _ingest_candidate_impl(candidate_id, None)


def _ingest_with_lock_armor(candidate_id: int, rep: Any) -> dict[str, Any]:
    """Run one candidate load, riding out transient 'database is locked'
    storms (§74j owner complaint): calm progress message, backoff, retry —
    the load completes without the owner ever re-clicking Load.

    Shared by the legacy worker AND the sequential load queue, so every
    load path is armored identically. Must be called inside an active
    load_progress.bind(rep) context so the calm message reaches the UI.
    """
    import sqlite3 as _sqlite3
    import time as _time

    result: dict[str, Any] | None = None
    for attempt in range(3):
        try:
            result = _ingest_candidate_impl(candidate_id, rep)
            break
        except _sqlite3.OperationalError as ex:
            if "locked" not in str(ex).lower() or attempt >= 2:
                raise
            wait_s = 8 * (attempt + 1)
            load_progress.stage(
                "finalize",
                f"Library busy — waiting {wait_s}s for the lock to clear "
                f"and retrying (attempt {attempt + 2} of 3). "
                "Your download is queued and safe; no action needed.",
            )
            _time.sleep(wait_s)
    return result or {"ok": False, "error": "load produced no result"}


def _ingest_candidate_worker(candidate_id: int, job_id: str) -> None:
    """Run the load in this background thread with progress bound."""
    _rep = load_progress.job_reporter(job_id)
    try:
        with load_progress.bind(_rep):
            result = _ingest_with_lock_armor(candidate_id, _rep)
        load_progress.finish_job(job_id, result)
    except load_progress.LoadCancelled as ex:
        load_progress.error_job(job_id, str(ex) or "Cancelled by owner.")
    except HTTPException as ex:
        load_progress.error_job(job_id, str(ex.detail or ex))
    except Exception as ex:
        load_progress.error_job(job_id, str(ex) or ex.__class__.__name__)


def _resolve_target_field(candidate_id: int, candidate: dict[str, Any], metadata: dict[str, Any]) -> tuple[str, str]:
    """Resolve the target field, healing old rows that stored the field's
    detail string, display name, or empty string instead of the canonical slug."""
    from .sentinel_domains import sanitize_field_and_domain

    field_text = str(candidate.get("scientific_field") or metadata.get("field_slug") or metadata.get("scientific_field") or "").strip()
    fallback_text = " ".join(
        str(x or "")
        for x in (
            metadata.get("search_query"),
            metadata.get("query"),
            metadata.get("oa_field"),
            metadata.get("oa_subfield"),
            metadata.get("oa_topic"),
            candidate.get("title"),
            candidate.get("description"),
        )
    )
    field_slug, _ = sanitize_field_and_domain(field_text, fallback_text=fallback_text)
    field = field_slug or field_text
    if not field:
        raise HTTPException(status_code=400, detail="Candidate has no scientific field set.")
    if field_slug and field_slug != str(candidate.get("scientific_field") or "").strip():
        try:
            with get_connection() as heal_conn:
                heal_conn.execute(
                    "UPDATE skill_review_candidates SET scientific_field = ? WHERE id = ?",
                    (field_slug, candidate_id),
                )
                heal_conn.commit()
        except Exception:
            pass
    return field, field_slug


def _ingest_candidate_impl(candidate_id: int, rep: Any) -> dict[str, Any]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM skill_review_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    candidate = dict(row)
    from .openalex_worker import load_openalex_works_into_field
    from .sentinel_domains import (
        ingest_github_dataset_to_field,
        ingest_huggingface_dataset_to_field,
        slugify,
    )

    metadata_raw = candidate.get("metadata_json") or "{}"
    try:
        metadata = json.loads(metadata_raw) if isinstance(metadata_raw, str) else dict(metadata_raw or {})
    except Exception:
        metadata = {}
    # Legacy PubMed rows carry the ids nested under _metadata; accept both
    # shapes so the load lane always sees pmid/pmcid/doi.
    nested_meta = metadata.get("_metadata") if isinstance(metadata.get("_metadata"), dict) else {}
    for _k in ("pmid", "pmcid", "doi"):
        if not metadata.get(_k) and nested_meta.get(_k):
            metadata[_k] = str(nested_meta[_k])
    source_type = str(candidate.get("source_type") or "").strip().lower()

    field, field_slug = _resolve_target_field(candidate_id, candidate, metadata)
    _SOURCE_LABELS = {
        "github": "GitHub",
        "huggingface": "Hugging Face",
        "openalex": "OpenAlex",
        "eu_data_portal": "European Data Portal",
        "pubmed": "NLM / NHLBI / PubMed",
        "worldbank": "World Bank (Official Indicators & DBnomics)",
        "eurostat": "Eurostat (European Union Statistics SDMX 2.1)",
        "imf": "IMF (International Monetary Fund Finances)",
        "ecb": "ECB (European Central Bank Financial Data)",
        "bis": "BIS (Bank for International Settlements)",
        "undata": "UN Data (United Nations Statistical Division)",
        "bea": "U.S. BEA (Bureau of Economic Analysis)",
        "oecd": "OECD (Official Statistics)",
        "contemporary": "Scraped Contemporary Sources",
        "contemporary-journal": "Scraped Contemporary Sources",
        "contemporary-article": "Scraped Contemporary Sources",
        "contemporary-preprint": "Scraped Contemporary Sources",
    }
    _source_label = _SOURCE_LABELS.get(source_type, source_type or "the source")
    load_progress.emit_meta(
        field=field_slug,
        source_type=source_type,
        title=str(candidate.get("title") or ""),
        label=f"Load {_source_label} candidate {candidate_id}",
    )
    load_progress.stage(
        "download",
        f'Downloading "{str(candidate.get("title") or "candidate")[:60]}" from {_source_label}...',
    )

    result: dict[str, Any]
    if source_type == "github":
        load_progress.stage("download", f"Fetching repository files from GitHub for {field_slug}...")
        result = ingest_github_dataset_to_field(field, [str(candidate.get("source_url") or "")], max_files_per_repo=200, max_total_mb=300)
        result["source_type"] = "github"
    elif source_type == "huggingface":
        source_url = str(candidate.get("source_url") or "")
        dataset = source_url.split("/datasets/")[1] if "/datasets/" in source_url else str(metadata.get("dataset") or candidate.get("title") or "")
        result = ingest_huggingface_dataset_to_field(field, dataset.strip("/"), config_name="default", split="train", rows=50)
        result["source_type"] = "huggingface"
    elif source_type == "pubmed":
        load_progress.stage("download", "Fetching the paper from PubMed Central (open access) or NLM PubMed...")
        from .pubmed_worker import load_pubmed_papers_into_field

        result = load_pubmed_papers_into_field(
            field,
            [
                {
                    "pmid": str(metadata.get("pmid") or _pmid_from_url(str(candidate.get("source_url") or ""))),
                    "pmcid": str(metadata.get("pmcid") or ""),
                    "title": str(candidate.get("title") or ""),
                }
            ],
            max_papers=1,
        )
        result["source_type"] = "pubmed"
    elif source_type == "eu_data_portal":
        load_progress.stage("download", "Preparing the selected EU dataset metadata for the research library...")
        from .eu_portal_search import ingest_eu_dataset_metadata_into_field

        result = ingest_eu_dataset_metadata_into_field(field, metadata)
        result["source_type"] = "eu_data_portal"
    elif source_type == "worldbank":
        load_progress.stage("download", "Fetching the dataset from World Bank Official API / DBnomics...")
        from .worldbank_worker import load_dbnomics_dataset_into_field

        result = load_dbnomics_dataset_into_field(
            field,
            {
                "provider": str(metadata.get("provider") or "WB"),
                "dataset": str(metadata.get("dataset") or ""),
                "indicator": str(metadata.get("indicator") or ""),
                "title": str(candidate.get("title") or ""),
                "description": str(candidate.get("description") or ""),
                "source_url": str(candidate.get("source_url") or ""),
                "query": str(metadata.get("query") or ""),
            },
        )
        result["source_type"] = "worldbank"
    elif source_type in {"eurostat", "imf", "ecb", "bis", "undata", "bea"}:
        load_progress.stage("download", f"Fetching observations from {_source_label}...")
        from .intl_stats_worker import load_intl_stat_dataset_into_field

        result = load_intl_stat_dataset_into_field(
            field,
            source_type,
            {
                "agency": str(metadata.get("agency") or source_type.upper()),
                "dataset": str(metadata.get("dataset") or ""),
                "indicator": str(metadata.get("indicator") or ""),
                "version": str(metadata.get("version") or "1.0"),
                "title": str(candidate.get("title") or ""),
                "description": str(candidate.get("description") or ""),
                "source_url": str(candidate.get("source_url") or ""),
                "query": str(metadata.get("query") or ""),
            },
        )
        result["source_type"] = source_type
    elif source_type == "oecd":
        load_progress.stage("download", "Fetching OECD SDMX observations and structure...")
        from .oecd_worker import load_oecd_dataset_into_field

        result = load_oecd_dataset_into_field(
            field,
            {
                "agency": str(metadata.get("agency") or "OECD"),
                "dataset": str(metadata.get("dataset") or ""),
                "version": str(metadata.get("version") or "1.0"),
                "query": str(metadata.get("query") or ""),
            },
        )
        result["source_type"] = "oecd"
    elif source_type in {"contemporary", "contemporary-journal", "contemporary-article", "contemporary-preprint"}:
        load_progress.stage("download", "Scraping and ingesting Contemporary Source article/journal...")
        from .contemporary_scraper import load_contemporary_candidate_into_field

        merged_cand = {**metadata, **candidate}
        result = load_contemporary_candidate_into_field(merged_cand, field)
        result["source_type"] = "contemporary"
    else:
        load_progress.stage("download", "Fetching the work from OpenAlex (PDF, landing page, or record)...")
        work = {
            "openalex_id": str(metadata.get("openalex_id") or ""),
            "title": candidate.get("title"),
            "pdf_url": str(metadata.get("pdf_url") or ""),
            "landing_page_url": str(metadata.get("landing_page_url") or ""),
        }
        result = load_openalex_works_into_field(field, [work], max_works=1)
        result["source_type"] = "openalex"

    # Persist the outcome on the candidate and link the stored document(s).
    load_progress.stage("finalize", "Recording the loaded dataset in the field...")
    ingested = int(result.get("ingested") or 0)
    document_ids: list[int] = []
    document_titles: list[str] = []
    for item in result.get("items") or []:
        if isinstance(item, dict) and item.get("ok") and int(item.get("document_id") or 0) > 0:
            document_ids.append(int(item["document_id"]))
            if item.get("title"):
                document_titles.append(str(item["title"]))
    loaded_ok = ingested > 0
    if loaded_ok and not document_ids:
        # GitHub/HF lanes report repo-level summaries without per-file ids;
        # link one document from this batch by its stored path pattern.
        like_patterns: list[str] = []
        if source_type == "github":
            match = re.search(r"github\.com[/:]([^/]+)/([^/#?]+)", str(candidate.get("source_url") or ""))
            if match:
                folder = slugify(f"{match.group(1)}-{match.group(2)}")
                like_patterns = [f"%github/{folder}%", f"%github\\{folder}%"]
        elif source_type == "huggingface":
            source_url = str(candidate.get("source_url") or "")
            dataset = source_url.split("/datasets/")[1] if "/datasets/" in source_url else str(candidate.get("title") or "")
            like_patterns = [f"%hf-{slugify(dataset.strip('/'))}%"]
        elif source_type == "pubmed":
            pmid = str(metadata.get("pmid") or _pmid_from_url(str(candidate.get("source_url") or "")))
            if pmid:
                like_patterns = [f"%pm{slugify(pmid)}%"]
        elif source_type == "oecd":
            dataset = str(metadata.get("dataset") or "")
            if dataset:
                like_patterns = [f"%oecd-{slugify(dataset)}%"]
        try:
            if like_patterns:
                with library_connection("gemma") as conn:
                    for pattern in like_patterns:
                        row = conn.execute(
                            "SELECT id, title FROM documents WHERE scientific_field = ? AND source_path LIKE ? ORDER BY id DESC LIMIT 1",
                            (field_slug, pattern),
                        ).fetchone()
                        if row is not None:
                            document_ids = [int(row["id"])]
                            document_titles = [str(row["title"] or "")]
                            break
        except Exception:
            pass
    update_error: Exception | None = None
    import sqlite3 as _sqlite3
    import time as _time

    from .config import get_settings
    from .db import _db_path

    for _attempt in range(20):
        now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        try:
            with get_connection() as conn:
                conn.execute(
                    """
                    UPDATE skill_review_candidates
                    SET status = ?, reviewed_at = ?,
                        loaded_document_id = ?, loaded_title = ?, loaded_at = CASE WHEN ? > 0 THEN ? ELSE loaded_at END
                    WHERE id = ?
                    """,
                    (
                        "loaded" if loaded_ok else "failed",
                        now_iso,
                        document_ids[0] if document_ids else None,
                        (document_titles[0] if document_titles else (str(candidate.get("title") or "") or result.get("field") or "")),
                        1 if loaded_ok else 0,
                        now_iso,
                        candidate_id,
                    ),
                )
                conn.commit()
            update_error = None
            break
        except Exception as ex:
            if "locked" not in str(ex).lower():
                raise
            update_error = ex
            _time.sleep(0.5)
    if update_error is not None:
        raise update_error
    if not loaded_ok:
        # Owner directive: a failed load must leave NOTHING behind — partial
        # documents/chunks are purged from the field's library, and the
        # dataset is recorded as rejected so it can never reappear in a
        # future search or be re-loaded in this broken state.
        try:
            from .sentinel_domains import purge_field_documents

            attempt_doc_ids = [
                int(item.get("document_id"))
                for item in (result.get("items") or [])
                if isinstance(item, dict) and int(item.get("document_id") or 0) > 0
            ]
            purge_field_documents(field_slug, attempt_doc_ids)
        except Exception:
            pass
        try:
            from .pattern_store import remember_rejected_identity

            _failed_identity = str(candidate.get("identity_key") or "")
            if _failed_identity:
                remember_rejected_identity(_failed_identity)
        except Exception:
            pass
    result["candidate_id"] = candidate_id
    result["candidate_status"] = "loaded" if loaded_ok else "failed"
    result["document_id"] = document_ids[0] if document_ids else None
    result["loaded_title"] = document_titles[0] if document_titles else ""
    return result


@router.get("/load-queue")
def load_queue_status() -> dict[str, Any]:
    """Live status of the sequential background load queue (owner directive)."""
    from .load_queue import get_load_queue

    return get_load_queue().snapshot()


@router.post("/load-queue/{entry_id}/cancel")
def load_queue_cancel(entry_id: str) -> dict[str, Any]:
    """Cancel a queued entry instantly or request a running load to stop."""
    from .load_queue import get_load_queue

    outcome = get_load_queue().cancel(entry_id)
    if not outcome.get("ok"):
        raise HTTPException(status_code=404, detail=str(outcome.get("error") or "Unknown queue entry."))
    return outcome


@router.get("/progress/{job_id}")
def load_job_progress(job_id: str) -> dict[str, Any]:
    """Live progress for a background Load job (download / digest / embed)."""
    snapshot = load_progress.job_snapshot(job_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Unknown load job.")
    return snapshot


@router.post("/candidates/{candidate_id}/review")
def review_candidate(
    candidate_id: int,
    decision: str = Query(..., pattern="^(approve|reject)$"),
) -> dict[str, Any]:
    _ensure_schema()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM skill_review_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Skill candidate not found.")
        if decision == "reject":
            # Rejected datasets are removed from the review lineup immediately
            # (owner directive). The identity_key is preserved in the worker's
            # rejected-identity cache, so it will never reappear in future
            # searches either — only a fresh Load via GitHub/HF direct pull
            # can reintroduce the same dataset.
            identity = str(row["identity_key"] or "")
            conn.execute("DELETE FROM skill_review_candidates WHERE id = ?", (candidate_id,))
            conn.commit()
            if identity:
                try:
                    from .pattern_store import remember_rejected_identity

                    remember_rejected_identity(identity)
                    # Also block same-title variants: the same work often
                    # resurfaces under a different URL (mirrors, DOI vs landing
                    # page) — identical titles must not dodge the cache.
                    title_key = _source_identity(str(row["source_type"] or ""), "", {}, str(row["title"] or ""))
                    if title_key and title_key != identity:
                        remember_rejected_identity(title_key)
                except Exception:
                    pass
            return {
                "ok": True,
                "candidate_id": candidate_id,
                "status": "reject",
                "removed": True,
                "activated": False,
                "shared_skills_root": str(_root()),
            }
        now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        conn.execute(
            "UPDATE skill_review_candidates SET status = ?, reviewed_at = ? WHERE id = ?",
            (decision, now_iso, candidate_id),
        )
        conn.commit()

    if decision == "approve":
        manifest_dir = _root() / "approved"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest = manifest_dir / f"candidate-{candidate_id}.json"
        manifest.write_text(
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "source_url": row["source_url"],
                    "source_type": row["source_type"],
                    "title": row["title"],
                    "scientific_field": row["scientific_field"],
                    "target_persona": row["target_persona"],
                    "license": row["license"],
                    "approved_for_review": True,
                    "activated": False,
                },
                ensure_ascii=True,
                indent=2,
            ),
            encoding="utf-8",
        )
    return {
        "ok": True,
        "candidate_id": candidate_id,
        "status": decision,
        "activated": False,
        "shared_skills_root": str(_root()),
    }


@router.post("/candidates/{candidate_id}/test")
def test_candidate(candidate_id: int) -> dict[str, Any]:
    _ensure_schema()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM skill_review_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Skill candidate not found.")
    result = {
        "ok": True,
        "candidate": dict(row),
        "test_status": "queued_for_manual_test",
        "activated": False,
    }
    # OpenAlex works can be dry-run tested: fetch metadata + report what would load.
    candidate = dict(row)
    if str(candidate.get("source_type") or "") == "openalex":
        metadata_raw = candidate.get("metadata_json") or "{}"
        try:
            metadata = json.loads(metadata_raw) if isinstance(metadata_raw, str) else dict(metadata_raw or {})
        except Exception:
            metadata = {}
        result["test_report"] = {
            "would_download_pdf": bool(metadata.get("pdf_url")),
            "pdf_url": str(metadata.get("pdf_url") or ""),
            "landing_page_url": str(metadata.get("landing_page_url") or ""),
            "open_access": bool(metadata.get("is_oa")),
            "note": "Dry run only: nothing was downloaded or ingested.",
        }
    return result
