"""Local index and report helpers for the IMD World Competitiveness 2026 booklet."""

from __future__ import annotations

import hashlib
import html
import os
import re
import sqlite3
import threading
import unicodedata
from contextlib import closing
from pathlib import Path
from typing import Any

from pypdf import PdfReader

INDEX_VERSION = "imd-wcy-2026-v1"
SOURCE_TITLE = "IMD World Competitiveness Yearbook 2026 booklet"
SOURCE_CITATION = "IMD World Competitiveness Yearbook 2026, pp. 65-68, 66-67, 76-83, 86-87."

FACTOR_DEFINITIONS = (
    ("economic_performance", "Economic Performance", (76, 77)),
    ("government_efficiency", "Government Efficiency", (78, 79)),
    ("business_efficiency", "Business Efficiency", (80, 81)),
    ("infrastructure", "Infrastructure", (82, 83)),
)

SUBFACTORS = (
    "Domestic Economy",
    "International Trade",
    "International Investment",
    "Employment",
    "Prices",
    "Public Finance",
    "Tax Policy",
    "Institutional Framework",
    "Business Legislation",
    "Societal Framework",
    "Productivity & Efficiency",
    "Labor Market",
    "Finance",
    "Management Practices",
    "Attitudes & Values",
    "Basic Infrastructure",
    "Technological Infrastructure",
    "Scientific Infrastructure",
    "Health & Environment",
    "Education",
)

_COUNTRY_ALIASES: dict[str, tuple[str, ...]] = {
    "UAE": ("United Arab Emirates",),
    "USA": ("United States", "United States of America", "US", "U.S.", "U.S.A."),
    "Hong Kong SAR": ("Hong Kong",),
    "Taiwan (Chinese Taipei)": ("Taiwan", "Chinese Taipei"),
    "Korea Rep.": ("South Korea", "Republic of Korea", "Korea, Republic of"),
    "Türkiye": ("Turkey", "Turkiye"),
    "Slovak Republic": ("Slovakia",),
}
_INDEX_LOCK = threading.RLock()
_SCORE_ROW = re.compile(r"^\s*(\d{1,2})\s+(.+?)\s+(\d{1,3}\.\d{2})(?:\s+.*)?$")
_RANK_SEQUENCE = re.compile(r"^\s*((?:\d{1,2}\s+){9}\d{1,2})\s+(.+?)\s*$")


class GCIIndexError(RuntimeError):
    """Raised when the supplied booklet does not contain the expected tables."""


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = decomposed.encode("ascii", errors="ignore").decode("ascii")
    return "".join(char.lower() for char in ascii_value if char.isalnum())


def resolve_pdf_path(pdf_path: str | Path | None = None) -> Path:
    explicit = pdf_path or os.environ.get("SENTINARI_GCI_PDF")
    if explicit:
        return Path(explicit).expanduser()

    root = Path(__file__).resolve().parents[1]
    candidates = [root / "gci" / "Booklet_WCY_2026.pdf"]
    if os.name == "nt":
        candidates.append(Path(r"D:\sentinari\gci\Booklet_WCY_2026.pdf"))
    return next((candidate for candidate in candidates if candidate.is_file()), candidates[0])


def default_index_path() -> Path:
    configured = os.environ.get("SENTINARI_GCI_INDEX_DB")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[1] / "data" / "gci" / "imd_wcy_2026.sqlite3"


def _read_booklet_pages(pdf_path: str | Path) -> list[str]:
    try:
        reader = PdfReader(str(pdf_path))
    except Exception as ex:
        from pypdf.errors import PdfReadError

        if isinstance(ex, (PdfReadError, OSError)):
            raise GCIIndexError(f"Could not read the supplied IMD booklet: {ex}") from ex
        raise
    return [page.extract_text() or "" for page in reader.pages]


def _parse_score_rows(lines: list[str], page_number: int) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for line in lines:
        match = _SCORE_ROW.match(line)
        if not match:
            continue
        rank, country, score = match.groups()
        country = country.strip()
        numeric_score = float(score)
        if not country or not 0 <= numeric_score <= 100:
            continue
        row = {
            "rank": int(rank),
            "score": numeric_score,
            "page": page_number,
        }
        previous = rows.get(country)
        if previous and (previous["rank"] != row["rank"] or previous["score"] != row["score"]):
            raise GCIIndexError(f"Conflicting ranking rows for {country} on page {page_number}.")
        rows[country] = row
    return rows


def _parse_subfactor_page(
    lines: list[str],
    country_names: list[str],
    *,
    reverse_layout: bool,
    page_number: int,
) -> dict[str, list[int]]:
    rows: dict[str, list[int]] = {}
    ordered_countries = sorted(country_names, key=len, reverse=True)
    for line in lines:
        country: str | None = None
        rank_text = ""
        if reverse_layout:
            match = _RANK_SEQUENCE.match(line)
            if not match:
                continue
            rank_text, suffix = match.groups()
            suffix = suffix.strip()
            country = next((name for name in ordered_countries if suffix == name), None)
            if country is None:
                continue
        else:
            country = next(
                (name for name in ordered_countries if line.startswith(name + " ")),
                None,
            )
            if country is None:
                continue
            rank_text = line[len(country):].strip()

        values = [int(value) for value in re.findall(r"\d{1,2}", rank_text)]
        if len(values) != 10 or any(value < 1 or value > 70 for value in values):
            raise GCIIndexError(f"Expected ten valid sub-factor ranks for {country} on page {page_number}.")
        rows[country] = values

    if len(rows) != len(country_names):
        raise GCIIndexError(
            f"Expected {len(country_names)} country rows on page {page_number}; found {len(rows)}."
        )
    return rows


def parse_booklet_pages(pages: list[str]) -> dict[str, dict[str, Any]]:
    """Parse extracted PDF page text; page numbers in results are one-based."""
    if len(pages) < 87:
        raise GCIIndexError(f"Expected at least 87 PDF pages; found {len(pages)}.")

    overall: dict[str, dict[str, Any]] = {}
    for page_number in (66, 67):
        overall.update(_parse_score_rows(pages[page_number - 1].splitlines(), page_number))
    if len(overall) != 70:
        raise GCIIndexError(f"Expected 70 overall ranking rows; found {len(overall)}.")

    country_names = list(overall)
    countries: dict[str, dict[str, Any]] = {
        country: {
            "country": country,
            "overall_rank": row["rank"],
            "overall_score": row["score"],
            "overall_page": row["page"],
            "dimensions": [],
        }
        for country, row in overall.items()
    }

    for slug, factor_name, page_numbers in FACTOR_DEFINITIONS:
        factor_rows: dict[str, dict[str, Any]] = {}
        for page_number in page_numbers:
            factor_rows.update(_parse_score_rows(pages[page_number - 1].splitlines(), page_number))
        if len(factor_rows) != 70:
            raise GCIIndexError(
                f"Expected 70 {factor_name} rows; found {len(factor_rows)}."
            )
        for country in country_names:
            row = factor_rows.get(country)
            if row is None:
                raise GCIIndexError(f"Missing {factor_name} ranking for {country}.")
            countries[country]["dimensions"].append({
                "slug": slug,
                "name": factor_name,
                "kind": "factor",
                "rank": row["rank"],
                "score": row["score"],
                "source_page": row["page"],
            })

    first_subfactors = SUBFACTORS[:10]
    second_subfactors = SUBFACTORS[10:]
    first_rows = _parse_subfactor_page(
        pages[85].splitlines(),
        country_names,
        reverse_layout=False,
        page_number=86,
    )
    second_rows = _parse_subfactor_page(
        pages[86].splitlines(),
        country_names,
        reverse_layout=True,
        page_number=87,
    )
    for country in country_names:
        for names, ranks, page_number in (
            (first_subfactors, first_rows[country], 86),
            (second_subfactors, second_rows[country], 87),
        ):
            for name, rank in zip(names, ranks):
                countries[country]["dimensions"].append({
                    "slug": _fold(name),
                    "name": name,
                    "kind": "subfactor",
                    "rank": rank,
                    "score": None,
                    "source_page": page_number,
                })
    return countries


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS gci_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS gci_countries (
            country TEXT PRIMARY KEY,
            overall_rank INTEGER NOT NULL,
            overall_score REAL NOT NULL,
            overall_page INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS gci_dimensions (
            country TEXT NOT NULL REFERENCES gci_countries(country) ON DELETE CASCADE,
            slug TEXT NOT NULL,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            rank INTEGER NOT NULL,
            score REAL,
            source_page INTEGER NOT NULL,
            PRIMARY KEY (country, slug)
        );
        """
    )
    conn.commit()


def _metadata_value(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM gci_metadata WHERE key = ?", (key,)).fetchone()
    return str(row[0]) if row else None


def ensure_index(
    *,
    pdf_path: str | Path | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    source = resolve_pdf_path(pdf_path)
    if not source.is_file():
        raise FileNotFoundError(f"IMD 2026 booklet not found: {source}")
    index_path = Path(db_path) if db_path else default_index_path()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    source_hash = _digest_file(source)

    with _INDEX_LOCK:
        conn = sqlite3.connect(index_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            _create_schema(conn)
            if (
                _metadata_value(conn, "source_sha256") == source_hash
                and _metadata_value(conn, "index_version") == INDEX_VERSION
            ):
                return {
                    "indexed": True,
                    "economies": int(conn.execute("SELECT COUNT(*) FROM gci_countries").fetchone()[0]),
                    "source": SOURCE_TITLE,
                    "updated": False,
                }

            parsed = parse_booklet_pages(_read_booklet_pages(source))
            conn.execute("BEGIN IMMEDIATE")
            if (
                _metadata_value(conn, "source_sha256") == source_hash
                and _metadata_value(conn, "index_version") == INDEX_VERSION
            ):
                conn.commit()
                return {
                    "indexed": True,
                    "economies": int(conn.execute("SELECT COUNT(*) FROM gci_countries").fetchone()[0]),
                    "source": SOURCE_TITLE,
                    "updated": False,
                }
            conn.execute("DELETE FROM gci_dimensions")
            conn.execute("DELETE FROM gci_countries")
            for country, row in parsed.items():
                conn.execute(
                    "INSERT INTO gci_countries(country, overall_rank, overall_score, overall_page) VALUES (?, ?, ?, ?)",
                    (country, row["overall_rank"], row["overall_score"], row["overall_page"]),
                )
                conn.executemany(
                    """
                    INSERT INTO gci_dimensions(country, slug, name, kind, rank, score, source_page)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            country,
                            dimension["slug"],
                            dimension["name"],
                            dimension["kind"],
                            dimension["rank"],
                            dimension["score"],
                            dimension["source_page"],
                        )
                        for dimension in row["dimensions"]
                    ],
                )
            conn.executemany(
                "INSERT OR REPLACE INTO gci_metadata(key, value) VALUES (?, ?)",
                [
                    ("source_sha256", source_hash),
                    ("source_name", source.name),
                    ("index_version", INDEX_VERSION),
                ],
            )
            conn.commit()
            return {
                "indexed": True,
                "economies": len(parsed),
                "source": SOURCE_TITLE,
                "updated": True,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _open_index(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else default_index_path()
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _country_from_alias(value: str) -> str | None:
    folded = _fold(value)
    for canonical, aliases in _COUNTRY_ALIASES.items():
        if folded == _fold(canonical) or any(folded == _fold(alias) for alias in aliases):
            return canonical
    return None


def search_countries(
    query: str = "",
    *,
    limit: int = 70,
    pdf_path: str | Path | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_index(pdf_path=pdf_path, db_path=db_path)
    query_folded = _fold(query)
    with closing(_open_index(db_path)) as conn:
        rows = conn.execute(
            "SELECT country, overall_rank, overall_score FROM gci_countries ORDER BY overall_rank"
        ).fetchall()
    if query_folded:
        exact = _country_from_alias(query)
        if exact:
            rows = [row for row in rows if row["country"] == exact]
        else:
            rows = [
                row for row in rows
                if query_folded in _fold(str(row["country"]))
                or any(query_folded in _fold(alias) for alias in _COUNTRY_ALIASES.get(str(row["country"]), ()))
            ]
    return [
        {
            "country": str(row["country"]),
            "overall_rank": int(row["overall_rank"]),
            "overall_score": float(row["overall_score"]),
        }
        for row in rows[: max(1, min(int(limit), 70))]
    ]


def get_country(
    country: str,
    *,
    pdf_path: str | Path | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    ensure_index(pdf_path=pdf_path, db_path=db_path)
    canonical = _country_from_alias(country) or country.strip()
    with closing(_open_index(db_path)) as conn:
        row = conn.execute(
            "SELECT country, overall_rank, overall_score, overall_page FROM gci_countries WHERE country = ? COLLATE NOCASE",
            (canonical,),
        ).fetchone()
        if row is None:
            return None
        dimensions = conn.execute(
            """
            SELECT slug, name, kind, rank, score, source_page
            FROM gci_dimensions WHERE country = ?
            ORDER BY CASE kind WHEN 'factor' THEN 0 ELSE 1 END, rowid
            """,
            (row["country"],),
        ).fetchall()
    return {
        "country": str(row["country"]),
        "overall_rank": int(row["overall_rank"]),
        "overall_score": float(row["overall_score"]),
        "overall_page": int(row["overall_page"]),
        "dimensions": [
            {
                "slug": str(item["slug"]),
                "name": str(item["name"]),
                "kind": str(item["kind"]),
                "rank": int(item["rank"]),
                "score": float(item["score"]) if item["score"] is not None else None,
                "source_page": int(item["source_page"]),
            }
            for item in dimensions
        ],
        "source": SOURCE_TITLE,
        "source_citation": SOURCE_CITATION,
    }


def _country_mentions(text: str, country_names: list[str]) -> set[str]:
    mentions: set[str] = set()
    aliases: list[tuple[str, str]] = []
    for country in country_names:
        aliases.append((country, country))
        aliases.extend((alias, country) for alias in _COUNTRY_ALIASES.get(country, ()))
    for alias, canonical in sorted(aliases, key=lambda pair: len(pair[0]), reverse=True):
        folded_alias = _fold(alias)
        if len(folded_alias) < 4 and folded_alias not in {"uae", "usa"}:
            continue
        expression = re.escape(alias).replace(r"\ ", r"\s+")
        if re.search(rf"(?<![A-Za-z0-9]){expression}(?![A-Za-z0-9])", text, flags=re.IGNORECASE):
            mentions.add(canonical)
    return mentions


def _report_text(report: dict[str, Any], pattern: dict[str, Any] | None) -> str:
    parts: list[str] = []
    for item in (report, pattern or {}):
        for key in ("country", "country_name", "jurisdiction", "geography", "paper_title", "pattern_title", "title", "pattern_statement", "statement", "abstract"):
            value = item.get(key)
            if isinstance(value, str):
                parts.append(value)
        introduction = item.get("introduction_framework")
        if isinstance(introduction, dict):
            for key in ("problem_statement", "research_question", "hypothesis"):
                value = introduction.get(key)
                if isinstance(value, str):
                    parts.append(value)
    return "\n".join(parts)


def build_competitiveness_context(
    report: dict[str, Any],
    *,
    country: str | None = None,
    pattern: dict[str, Any] | None = None,
    pdf_path: str | Path | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    try:
        ensure_index(pdf_path=pdf_path, db_path=db_path)
    except FileNotFoundError as ex:
        return {"status": "unavailable", "message": str(ex)}
    except GCIIndexError as ex:
        return {"status": "unavailable", "message": str(ex)}

    candidates = search_countries("", pdf_path=pdf_path, db_path=db_path)
    country_names = [str(item["country"]) for item in candidates]
    selected: str | None = None
    mentions: set[str] = set()
    if country:
        selected = _country_from_alias(country)
        if selected is None:
            selected = next((name for name in country_names if _fold(name) == _fold(country)), None)
        if selected is None:
            return {
                "status": "not_found",
                "message": f"No 2026 IMD economy matches the selected country “{country}”.",
            }
    else:
        text = _report_text(report, pattern)
        for key in ("country", "country_name", "jurisdiction", "geography"):
            for item in (report, pattern or {}):
                value = item.get(key)
                if isinstance(value, str):
                    alias_match = _country_from_alias(value.strip())
                    if alias_match:
                        mentions.add(alias_match)
        if not mentions:
            mentions = _country_mentions(text, country_names)
        if len(mentions) == 1:
            selected = next(iter(mentions))
        elif len(mentions) > 1:
            return {
                "status": "ambiguous",
                "countries": sorted(mentions),
                "message": "Multiple IMD economies are mentioned; select one in the Global Competitiveness workspace.",
            }
        else:
            return {
                "status": "not_found",
                "message": "No unique IMD economy was identified; select the report country in the Global Competitiveness workspace.",
            }

    data = get_country(selected, pdf_path=pdf_path, db_path=db_path)
    if data is None:
        return {"status": "not_found", "message": f"No 2026 IMD data was found for {selected}."}
    factors = [item for item in data["dimensions"] if item["kind"] == "factor"]
    weakest = min(factors, key=lambda item: float(item["score"] or 0))
    strongest = max(factors, key=lambda item: float(item["score"] or 0))
    subfactors = [item for item in data["dimensions"] if item["kind"] == "subfactor"]
    lowest_ranked = max(subfactors, key=lambda item: int(item["rank"]))
    highest_ranked = min(subfactors, key=lambda item: int(item["rank"]))
    data.update({
        "status": "matched",
        "factors": factors,
        "subfactors": subfactors,
        "recommendation_context": (
            f"Use {weakest['name']} (rank {weakest['rank']}, score {weakest['score']:.2f}/100) "
            f"as a constraint to address and {strongest['name']} (rank {strongest['rank']}, "
            f"score {strongest['score']:.2f}/100) as a potential enabling condition. "
            f"Among the 20 sub-factors, {lowest_ranked['name']} is ranked {lowest_ranked['rank']} "
            f"and {highest_ranked['name']} is ranked {highest_ranked['rank']}. "
            "Use these rankings to contextualize—not replace or causally prove—the R&D findings; "
            "recommendations should remain grounded in the report's own evidence."
        ),
        "source_citation": SOURCE_CITATION,
    })
    return data


def render_competitiveness_html(context: dict[str, Any]) -> str:
    status = str(context.get("status") or "")
    if status != "matched":
        message = html.escape(str(context.get("message") or "Country context is not available."))
        candidates = context.get("countries")
        extra = ""
        if isinstance(candidates, list) and candidates:
            extra = "<p>Possible economies: " + ", ".join(html.escape(str(item)) for item in candidates) + ".</p>"
        return (
            '<section class="gci-context"><h2>IMD World Competitiveness 2026 context</h2>'
            f"<p>{message}</p>{extra}<p><a href='/ui/gci'>Open the Global Competitiveness workspace</a> "
            "to choose an economy.</p></section>"
        )

    country = html.escape(str(context["country"]))
    factors = context.get("factors") or []
    subfactors = context.get("subfactors") or []
    bars = "".join(
        "<div style='margin:10px 0'>"
        f"<div style='display:flex;justify-content:space-between;gap:12px'><b>{html.escape(str(item['name']))}</b>"
        f"<span>Rank {int(item['rank'])} · {float(item['score']):.2f}/100</span></div>"
        "<div style='height:10px;background:#e2e8f0;border-radius:6px;overflow:hidden'>"
        f"<div style='height:100%;width:{max(0, min(100, float(item['score']))):.2f}%;background:#2563eb'></div>"
        "</div></div>"
        for item in factors
    )
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(item['name']))}</td><td>{int(item['rank'])} / 70</td>"
        f"<td>p. {int(item['source_page'])}</td></tr>"
        for item in subfactors
    )
    rationale = html.escape(str(context.get("recommendation_context") or ""))
    citation = html.escape(str(context.get("source_citation") or SOURCE_CITATION))
    return (
        "<section class='gci-context' style='margin:24px 0;padding:20px;border:1px solid #cbd5e1;"
        "border-radius:12px;background:#f8fafc;color:#0f172a'>"
        f"<h2>Country competitiveness context: {country}</h2>"
        f"<p>Overall rank {int(context['overall_rank'])} of 70; index score {float(context['overall_score']):.2f}/100.</p>"
        "<h3>Four factor scores</h3>"
        f"{bars}<h3>Twenty sub-factor ranks (rank 1 is strongest)</h3>"
        "<div style='overflow-x:auto'><table style='border-collapse:collapse;width:100%'>"
        "<thead><tr><th align='left'>Sub-factor</th><th align='left'>Rank</th><th align='left'>Source</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
        f"<p><b>How this informs recommendations:</b> {rationale}</p>"
        f"<p><small>Source: {citation} Scores are indices and ranks are comparative; these results are context, not causal evidence. "
        "<a href='/ui/gci'>Open the Global Competitiveness workspace</a>.</small></p></section>"
    )


def build_country_pdf(country: str, *, pdf_path: str | Path | None = None, db_path: str | Path | None = None) -> bytes:
    data = get_country(country, pdf_path=pdf_path, db_path=db_path)
    if data is None:
        raise KeyError(country)
    factors = [item for item in data["dimensions"] if item["kind"] == "factor"]
    subfactors = [item for item in data["dimensions"] if item["kind"] == "subfactor"]
    lines = [
        f"IMD World Competitiveness Yearbook 2026 - {data['country']}",
        "",
        f"Overall rank: {data['overall_rank']} of 70 economies",
        f"Overall index score: {data['overall_score']:.2f} / 100",
        "",
        "FACTOR SCORES",
        "Ranks are comparative; scores are indices from 0 to 100.",
    ]
    lines.extend(
        f"{item['name']}: rank {item['rank']} of 70, score {float(item['score']):.2f}/100 (source p. {item['source_page']})"
        for item in factors
    )
    lines.extend(["", "SUB-FACTOR RANKS", "Rank 1 is strongest; no sub-factor scores are supplied in the booklet."])
    lines.extend(
        f"{item['name']}: rank {item['rank']} of 70 (source p. {item['source_page']})"
        for item in subfactors
    )
    lines.extend([
        "",
        "INTERPRETATION",
        "Use these rankings as descriptive context for research and recommendations, not as causal evidence.",
        "",
        f"Source: {SOURCE_CITATION}",
        "Generated from the locally indexed booklet supplied by the user. No source PDF pages are reproduced.",
    ])
    from .text_pdf import build_pdf_bytes

    return build_pdf_bytes("\n".join(lines), title=f"IMD Competitiveness 2026 - {data['country']}")
