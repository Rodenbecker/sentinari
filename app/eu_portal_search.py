from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests

from .config import get_project_root

EU_PORTAL_SEARCH_URL = "https://data.europa.eu/api/hub/search/search"
_SEARCH_INCLUDES = (
    "id,title,description,modified,issued,distributions,resource,publisher,catalog"
)


class EuPortalSearchError(RuntimeError):
    pass


def _plain_text(value: Any) -> str:
    if isinstance(value, dict):
        english = next(
            (
                item
                for key, item in value.items()
                if str(key).lower() in {"en", "eng"}
                or str(key).lower().startswith("en-")
            ),
            None,
        )
        if english is not None:
            return _plain_text(english)
        preferred = next(
            (value[key] for key in ("label", "name", "title") if value.get(key)),
            None,
        )
        if preferred is not None:
            return _plain_text(preferred)
        return _plain_text(next(iter(value.values()), ""))
    if isinstance(value, (list, tuple)):
        text = " ; ".join(_plain_text(item) for item in value if item)
    elif value is None:
        text = ""
    else:
        text = str(value)
    text = re.sub(r"<[^>]*>", " ", html.unescape(text))
    return re.sub(r"\s+", " ", text).strip()


def _safe_https_url(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 1024:
        return None
    url = value.strip()
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or port not in (None, 443)
    ):
        return None
    return url


def _dataset_resource_url(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 1024:
        return None
    try:
        parsed = urlparse(value.strip())
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.hostname == "data.europa.eu"
        and parsed.scheme in {"http", "https"}
        and not parsed.username
        and not parsed.password
        and port in (None, 80, 443)
    ):
        return urlunparse(("https", "data.europa.eu", parsed.path, "", parsed.query, parsed.fragment))
    return _safe_https_url(value)


def _normalize_distribution(raw: Any) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    access_urls = raw.get("access_url")
    if isinstance(access_urls, str):
        access_urls = [access_urls]
    if not isinstance(access_urls, (list, tuple)):
        return None
    url = next(
        (
            safe_url
            for value in access_urls
            if (safe_url := _safe_https_url(value)) and len(safe_url) <= 500
        ),
        None,
    )
    if not url:
        return None
    return {
        "title": _plain_text(raw.get("title"))[:120] or "Dataset resource",
        "url": url,
        "format": _plain_text(raw.get("format"))[:80],
        "license": _plain_text(raw.get("license"))[:100],
    }


def _normalize_dataset(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    dataset_id = str(raw.get("id") or "").strip()
    source_url = _dataset_resource_url(raw.get("resource"))
    if not dataset_id or not source_url:
        return None

    raw_distributions = raw.get("distributions")
    distributions = []
    if isinstance(raw_distributions, list):
        for distribution in raw_distributions:
            normalized = _normalize_distribution(distribution)
            if normalized:
                distributions.append(normalized)
            if len(distributions) == 2:
                break

    publisher = _plain_text(raw.get("publisher"))[:300]
    license_name = _plain_text(raw.get("license"))[:200]
    if not license_name and distributions:
        license_name = next(
            (distribution["license"] for distribution in distributions if distribution["license"]),
            "",
        )
    return {
        "dataset_id": dataset_id[:200],
        "title": _plain_text(raw.get("title"))[:400] or dataset_id[:200],
        "description": _plain_text(raw.get("description"))[:1600],
        "source_url": source_url,
        "resource_uri": str(raw.get("resource") or "")[:1024],
        "publisher": publisher[:200],
        "catalogue": _plain_text(raw.get("catalog"))[:200],
        "issued": str(raw.get("issued") or "")[:40],
        "modified": str(raw.get("modified") or "")[:40],
        "license": license_name,
        "distributions": distributions,
    }


def search_eu_datasets(
    query: str,
    *,
    page: int = 0,
    limit: int = 15,
    from_year: int | None = None,
) -> dict[str, Any]:
    keyword = str(query or "").strip()
    if len(keyword) < 2 or len(keyword) > 200:
        raise ValueError("EU dataset search terms must contain 2 to 200 characters.")

    params: dict[str, Any] = {
        "q": keyword,
        "filters": "dataset",
        "page": max(0, int(page)),
        "limit": max(1, min(50, int(limit))),
        "includes": _SEARCH_INCLUDES,
    }
    if from_year is not None and 1500 <= int(from_year) <= 2100:
        params["minDate"] = f"{int(from_year)}-01-01T00:00:00Z"
        params["dateType"] = "issued"

    try:
        response = requests.get(
            EU_PORTAL_SEARCH_URL,
            params=params,
            headers={
                "Accept": "application/json",
                "User-Agent": "Sentinari/1.0 (EU public dataset discovery)",
            },
            timeout=(5, 25),
        )
    except requests.RequestException as exc:
        raise EuPortalSearchError("Could not reach the European Data Portal Search API.") from exc

    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        raise EuPortalSearchError("The European Data Portal Search API returned an error.") from exc
    try:
        response_data = response.json()
    except ValueError as exc:
        raise EuPortalSearchError("The European Data Portal returned invalid JSON.") from exc

    result = response_data.get("result") if isinstance(response_data, dict) else None
    raw_results = result.get("results") if isinstance(result, dict) else None
    if not isinstance(raw_results, list):
        raise EuPortalSearchError("The European Data Portal returned an unexpected response.")

    datasets = []
    for raw in raw_results:
        dataset = _normalize_dataset(raw)
        if dataset:
            datasets.append(dataset)
    return {
        "ok": True,
        "query": keyword,
        "page": params["page"],
        "count": len(datasets),
        "total_count": result.get("count", 0),
        "datasets": datasets,
        "source": "European Data Portal Search API",
    }


def ingest_eu_dataset_metadata_into_field(
    field: str,
    dataset: dict[str, Any],
) -> dict[str, Any]:
    dataset_id = re.sub(
        r"[^A-Za-z0-9._-]", "_", str(dataset.get("dataset_id") or "")
    ).strip("._-")
    if not dataset_id:
        raise ValueError("EU dataset has no valid identifier.")

    source_url = _dataset_resource_url(dataset.get("source_url"))
    if not source_url:
        raise ValueError("EU dataset is missing a valid European Data Portal link.")

    title = str(dataset.get("title") or f"EU dataset {dataset_id}").strip()
    description = str(dataset.get("description") or "").strip()
    publisher = str(dataset.get("publisher") or "").strip()
    catalogue = str(dataset.get("catalogue") or "").strip()
    issued = str(dataset.get("issued") or "").strip()
    modified = str(dataset.get("modified") or "").strip()
    distributions = dataset.get("distributions")
    if not isinstance(distributions, list):
        distributions = []

    content = [
        f"# {title}",
        "",
        "Source: data.europa.eu, the European Data Portal.",
        f"Dataset identifier: {dataset_id}",
    ]
    if publisher:
        content.append(f"Publisher: {publisher}")
    if catalogue:
        content.append(f"Catalogue: {catalogue}")
    if issued:
        content.append(f"Issued: {issued}")
    if modified:
        content.append(f"Modified: {modified}")
    content.extend(["", f"Dataset record: {source_url}"])
    for distribution in distributions[:2]:
        if not isinstance(distribution, dict):
            continue
        resource_url = _safe_https_url(distribution.get("url"))
        if not resource_url:
            continue
        details = [
            str(distribution.get("title") or "Dataset resource").strip(),
            str(distribution.get("format") or "").strip(),
            resource_url,
        ]
        if distribution.get("license"):
            details.append(f"License: {str(distribution['license']).strip()}")
        content.append("Resource: " + " | ".join(part for part in details if part))
    if description:
        content.extend(["", "## Dataset description", description])
    content.append(
        "\nThis record contains European Data Portal metadata and resource links. "
        "The linked data files are not downloaded automatically."
    )

    data_dir = get_project_root() / "data" / "research_sources" / "eu_data_portal"
    data_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = data_dir / f"{dataset_id}.md"
    metadata_path.write_text("\n".join(content) + "\n", encoding="utf-8")

    from .ingestion import ingest_files

    return ingest_files(
        [str(metadata_path)],
        metadata={
            "title": title,
            "source_type": "eu_data_portal",
            "source_url": source_url,
            "resource_uri": str(dataset.get("resource_uri") or source_url),
            "publisher": publisher or "European Data Portal",
            "published_date": issued[:10],
            "scientific_field": field,
            "topic": "European public datasets",
            "source_collection": "data.europa.eu",
            "license": str(dataset.get("license") or ""),
        },
    )
