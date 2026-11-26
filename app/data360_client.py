"""Small client for explicit, user-initiated World Bank Data360 requests."""

from __future__ import annotations

import re
from typing import Any

import requests

DATA360_ROOT = "https://data360api.worldbank.org"
DATA360_LICENSE = "Creative Commons Attribution 4.0 International (CC BY 4.0)"
_SEARCH_SELECT = (
    "series_description/idno, series_description/name, "
    "series_description/database_id"
)
_DATA_FIELDS = (
    "DATABASE_ID",
    "INDICATOR",
    "REF_AREA",
    "TIME_PERIOD",
    "OBS_VALUE",
    "UNIT_MEASURE",
    "UNIT_TYPE",
    "OBS_STATUS",
)


class Data360Error(RuntimeError):
    """Raised when Data360 returns an invalid response or cannot be reached."""


def _json_response(response: requests.Response) -> dict[str, Any]:
    try:
        response.raise_for_status()
    except requests.RequestException as ex:
        status = getattr(response, "status_code", None)
        raise Data360Error(f"Data360 request failed (HTTP {status or 'unavailable'}).") from ex
    try:
        payload = response.json()
    except ValueError as ex:
        raise Data360Error("Data360 returned invalid JSON.") from ex
    if not isinstance(payload, dict):
        raise Data360Error("Data360 returned an unexpected response shape.")
    return payload


def search_indicators(query: str, *, top: int = 10) -> dict[str, Any]:
    search = str(query or "").strip()
    if not search or len(search) > 200:
        raise ValueError("Search terms must contain 1–200 characters.")
    top = max(1, min(int(top), 25))
    try:
        response = requests.post(
            f"{DATA360_ROOT}/data360/searchv2",
            json={
                "search": search,
                "select": _SEARCH_SELECT,
                "top": top,
                "count": True,
            },
            headers={"Accept": "application/json"},
            timeout=20,
        )
    except requests.RequestException as ex:
        raise Data360Error("Could not reach the World Bank Data360 search service.") from ex
    payload = _json_response(response)
    raw_results = payload.get("value")
    if not isinstance(raw_results, list):
        raise Data360Error("Data360 search returned no result list.")
    results: list[dict[str, Any]] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        description = item.get("series_description")
        if not isinstance(description, dict):
            continue
        indicator_id = str(description.get("idno") or "").strip()
        dataset_id = str(description.get("database_id") or "").strip()
        name = str(description.get("name") or "").strip()
        if indicator_id and dataset_id and name:
            results.append({
                "indicator_id": indicator_id,
                "dataset_id": dataset_id,
                "name": name,
                "score": item.get("@search.score"),
            })
    count = payload.get("@odata.count", len(results))
    try:
        count = int(count)
    except (TypeError, ValueError):
        count = len(results)
    return {
        "query": search,
        "count": count,
        "results": results,
        "license": DATA360_LICENSE,
        "source_url": f"{DATA360_ROOT}/data360/searchv2",
    }


def get_indicator_data(
    database_id: str,
    indicator_id: str,
    country_code: str,
    *,
    period_from: str | None = None,
    period_to: str | None = None,
    latest: bool = True,
) -> dict[str, Any]:
    dataset = str(database_id or "").strip()
    indicator = str(indicator_id or "").strip()
    country = str(country_code or "").strip().upper()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", dataset):
        raise ValueError("Dataset ID must be 1–64 letters, digits, underscores, or hyphens.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", indicator):
        raise ValueError("Indicator ID must be 1–128 letters, digits, underscores, or hyphens.")
    if not re.fullmatch(r"[A-Z]{3}", country):
        raise ValueError("Country code must be a three-letter ISO-style code, such as USA.")
    for label, period in (("from", period_from), ("to", period_to)):
        if period is not None and not re.fullmatch(r"\d{4}", str(period)):
            raise ValueError(f"Time period {label} must be a four-digit year.")
    if period_from and period_to and int(period_from) > int(period_to):
        raise ValueError("Time period from must not be later than time period to.")
    params: dict[str, Any] = {
        "DATABASE_ID": dataset,
        "INDICATOR": indicator,
        "REF_AREA": country,
    }
    if period_from:
        params["timePeriodFrom"] = period_from
    if period_to:
        params["timePeriodTo"] = period_to
    if latest and not period_from and not period_to:
        params["isLatestData"] = "true"
    try:
        response = requests.get(
            f"{DATA360_ROOT}/data360/data",
            params=params,
            headers={"Accept": "application/json"},
            timeout=20,
        )
    except requests.RequestException as ex:
        raise Data360Error("Could not reach the World Bank Data360 data service.") from ex
    payload = _json_response(response)
    raw_results = payload.get("value")
    if not isinstance(raw_results, list):
        raise Data360Error("Data360 data response contained no result list.")
    rows = [
        {key: item.get(key) for key in _DATA_FIELDS if key in item}
        for item in raw_results
        if isinstance(item, dict)
    ]
    try:
        count = int(payload.get("count", len(rows)))
    except (TypeError, ValueError):
        count = len(rows)
    return {
        "count": count,
        "results": rows,
        "license": DATA360_LICENSE,
        "source_url": f"{DATA360_ROOT}/data360/data",
    }
