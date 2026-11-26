"""API routes for the local IMD competitiveness workspace and World Bank Data360."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from .data360_client import Data360Error, get_indicator_data, search_indicators
from .gci_index import (
    GCIIndexError,
    build_country_pdf,
    ensure_index,
    get_country,
    search_countries,
)

router = APIRouter(tags=["Competitiveness and Data360"])


class Data360SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    top: int = Field(default=10, ge=1, le=25)


def _index_http_error(ex: Exception) -> HTTPException:
    if isinstance(ex, FileNotFoundError):
        return HTTPException(status_code=503, detail=str(ex))
    return HTTPException(status_code=503, detail=f"Could not index the local IMD booklet: {ex}")


@router.get("/api/gci/status")
def gci_index_status() -> dict[str, Any]:
    try:
        return ensure_index()
    except (FileNotFoundError, GCIIndexError) as ex:
        raise _index_http_error(ex) from ex


@router.get("/api/gci/countries")
def gci_countries(
    q: str = Query(default="", max_length=80),
    limit: int = Query(default=70, ge=1, le=70),
) -> dict[str, Any]:
    try:
        countries = search_countries(q, limit=limit)
    except (FileNotFoundError, GCIIndexError) as ex:
        raise _index_http_error(ex) from ex
    return {"count": len(countries), "countries": countries}


@router.get("/api/gci/country")
def gci_country(country: str = Query(min_length=1, max_length=100)) -> dict[str, Any]:
    try:
        data = get_country(country)
    except (FileNotFoundError, GCIIndexError) as ex:
        raise _index_http_error(ex) from ex
    if data is None:
        raise HTTPException(status_code=404, detail="No 2026 IMD ranking was found for that economy.")
    return data


@router.get("/api/gci/report.pdf")
def gci_country_pdf(country: str = Query(min_length=1, max_length=100)) -> Response:
    try:
        content = build_country_pdf(country)
    except KeyError as ex:
        raise HTTPException(status_code=404, detail="No 2026 IMD ranking was found for that economy.") from ex
    except (FileNotFoundError, GCIIndexError) as ex:
        raise _index_http_error(ex) from ex
    filename = re.sub(r"[^A-Za-z0-9_-]+", "-", country).strip("-") or "economy"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="imd-wcy-2026-{filename}.pdf"'},
    )


@router.post("/api/playground/data360/search")
def data360_search(payload: Data360SearchRequest) -> dict[str, Any]:
    try:
        return search_indicators(payload.query, top=payload.top)
    except Data360Error as ex:
        raise HTTPException(status_code=502, detail=str(ex)) from ex
    except ValueError as ex:
        raise HTTPException(status_code=422, detail=str(ex)) from ex


@router.get("/api/playground/data360/data")
def data360_data(
    database_id: str = Query(min_length=1, max_length=64),
    indicator_id: str = Query(min_length=1, max_length=128),
    country_code: str = Query(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$"),
    period_from: str | None = Query(default=None, pattern=r"^\d{4}$"),
    period_to: str | None = Query(default=None, pattern=r"^\d{4}$"),
    latest: bool = Query(default=True),
) -> dict[str, Any]:
    try:
        return get_indicator_data(
            database_id,
            indicator_id,
            country_code,
            period_from=period_from,
            period_to=period_to,
            latest=latest,
        )
    except Data360Error as ex:
        raise HTTPException(status_code=502, detail=str(ex)) from ex
    except ValueError as ex:
        raise HTTPException(status_code=422, detail=str(ex)) from ex
