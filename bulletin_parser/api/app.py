"""
Read-only HTTP API for parsed bulletins.

Endpoints (all under /v1):
  GET  /parishes/{id}/today                — home-screen view
  GET  /parishes/{id}/bulletins/current    — full latest bulletin
  GET  /parishes/{id}/bulletins/{date}     — bulletin for a specific Sunday (YYYY-MM-DD)
  GET  /parishes/{id}/schedule             — services for the next N days, exceptions merged
  GET  /parishes/{id}                      — parish info
  GET  /parishes                           — listing (with optional ?near=lat,lng later)

Caching strategy:
  - ETag on every bulletin response, derived from content_sha256 we already store.
  - 304 Not Modified on If-None-Match match.
  - Cache-Control: public, max-age=3600, stale-while-revalidate=86400 for bulletin endpoints.
  - Today/schedule endpoints have shorter max-age (300s) because they're date-sensitive.

Auth: none. Bulletins are already public.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..harness.storage import Storage
from ..schema import Announcement, Bulletin, MassIntention, ScheduleException
from .repository import BulletinRecord, ParishSummary, Repository
from .views import DatedService, TodayView, schedule_view, today_view


# ---- Response models (FastAPI uses these to generate OpenAPI) -------------

class ParishResponse(BaseModel):
    id: str
    name: str
    diocese: str | None
    city: str | None
    state: str | None
    country: str
    timezone: str
    address: str | None = None
    postal_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    distance_km: float | None = None  # only set on /parishes?near=... results

    @classmethod
    def from_summary(cls, p: ParishSummary) -> "ParishResponse":
        return cls(
            id=p.id, name=p.name, diocese=p.diocese, city=p.city,
            state=p.state, country=p.country, timezone=p.timezone,
            address=p.address, postal_code=p.postal_code,
            latitude=p.latitude, longitude=p.longitude,
            distance_km=p.distance_km,
        )


class ParishListResponse(BaseModel):
    parishes: list[ParishResponse]
    count: int


class DatedServiceResponse(BaseModel):
    date: date
    start_time: str
    end_time: str | None
    kind: str
    language: str | None
    location_id: str
    notes: str | None
    is_exception: bool
    intentions: list[str]

    @classmethod
    def from_dated(cls, s: DatedService) -> "DatedServiceResponse":
        return cls(
            date=s.date,
            start_time=s.start_time.isoformat(timespec="minutes"),
            end_time=s.end_time.isoformat(timespec="minutes") if s.end_time else None,
            kind=s.kind.value,
            language=s.language.value if s.language else None,
            location_id=s.location_id,
            notes=s.notes,
            is_exception=s.is_exception,
            intentions=list(s.intentions),
        )


class TodayResponse(BaseModel):
    parish_id: str
    as_of: datetime
    today: date
    next_service: DatedServiceResponse | None
    today_services_remaining: list[DatedServiceResponse]
    this_week_exceptions: list[ScheduleException]
    high_priority_announcements: list[Announcement]
    todays_intentions: list[MassIntention]


class ScheduleResponse(BaseModel):
    parish_id: str
    days: int
    services: list[DatedServiceResponse]


# ---- App factory ---------------------------------------------------------

def create_app(storage: Storage) -> FastAPI:
    """Construct a FastAPI app bound to a given Storage.

    Factored as a function so tests can pass a temporary Storage without
    monkeypatching globals.
    """
    repo = Repository(storage)

    app = FastAPI(
        title="Catholic Bulletin API",
        version="0.1.0",
        description=(
            "Read-only access to parsed Catholic parish bulletins. "
            "Designed for mobile and web app consumption."
        ),
    )

    # FastAPI doesn't auto-add HEAD for GET routes, but CDNs and HTTP clients
    # use HEAD for cache validation. This middleware promotes HEAD to GET and
    # strips the body — saves us from duplicating every route declaration.
    @app.middleware("http")
    async def allow_head(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.method == "HEAD":
            request.scope["method"] = "GET"
            response = await call_next(request)
            # Body is intentionally not sent for HEAD; Starlette/Uvicorn handles
            # this when we just return the response. But we make sure Content-Length
            # reflects what GET would return.
            return response
        return await call_next(request)

    def get_repo() -> Repository:
        return repo

    # ---- Helpers -------------------------------------------------------

    def _etag_for(rec: BulletinRecord) -> str:
        # Strong ETag from the content hash. The bulletin JSON is a pure
        # function of the PDF + parser version; the content hash captures
        # the PDF, and parser version changes are reflected by re-parsing
        # (which creates a new parsed_bulletins row but doesn't change the
        # underlying PDF hash). For correctness we incorporate parsed_at.
        suffix = rec.parsed_at.isoformat()[:19]
        return f'"{rec.content_sha256}-{suffix}"'

    def _bulletin_cache_headers(rec: BulletinRecord) -> dict[str, str]:
        return {
            "ETag": _etag_for(rec),
            "Last-Modified": rec.fetched_at.astimezone(timezone.utc).strftime(
                "%a, %d %b %Y %H:%M:%S GMT"
            ),
            "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400",
        }

    def _today_cache_headers() -> dict[str, str]:
        # Shorter TTL — "today" changes at midnight in the parish timezone.
        return {"Cache-Control": "public, max-age=300, stale-while-revalidate=3600"}

    def _check_not_modified(request: Request, etag: str) -> bool:
        inm = request.headers.get("if-none-match")
        if not inm:
            return False
        # Handle comma-separated tags and weak prefixes
        candidates = [t.strip() for t in inm.split(",")]
        return etag in candidates or any(c.endswith(etag.strip('"')) for c in candidates)

    # ---- Routes --------------------------------------------------------

    @app.get("/v1/parishes", response_model=ParishListResponse, tags=["parishes"])
    def list_parishes(
        # Search modes — at most one should be set. If none are, the
        # endpoint returns a plain listing (the original behavior).
        q: str | None = None,
        postal_code: str | None = None,
        near: str | None = None,            # "lat,lng"
        radius_km: float = 25.0,
        # Generic params
        active_only: bool = True,
        limit: int = 100,
        repo: Repository = Depends(get_repo),
    ) -> ParishListResponse:
        # Exactly-one-mode rule keeps the endpoint predictable: clients
        # combining ?q= and ?near= would be confusing. We pick the most
        # specific provided rather than erroring, since this is read-only.
        if near:
            try:
                lat_s, lng_s = near.split(",")
                lat, lng = float(lat_s), float(lng_s)
            except (ValueError, AttributeError):
                raise HTTPException(
                    status_code=400,
                    detail="near must be 'lat,lng' (decimal degrees)",
                )
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                raise HTTPException(
                    status_code=400, detail="near coordinates out of range",
                )
            if radius_km <= 0 or radius_km > 500:
                raise HTTPException(
                    status_code=400, detail="radius_km must be in (0, 500]",
                )
            parishes = repo.search_by_location(lat, lng, radius_km=radius_km, limit=limit)
        elif postal_code:
            parishes = repo.search_by_postal_code(postal_code, limit=limit)
        elif q:
            parishes = repo.search_by_text(q, limit=limit)
        else:
            parishes = repo.list_parishes(active_only=active_only, limit=limit)
        return ParishListResponse(
            parishes=[ParishResponse.from_summary(p) for p in parishes],
            count=len(parishes),
        )

    @app.get("/v1/parishes/{parish_id}", response_model=ParishResponse, tags=["parishes"])
    def get_parish(parish_id: str, repo: Repository = Depends(get_repo)) -> ParishResponse:
        p = repo.get_parish(parish_id)
        if not p:
            raise HTTPException(status_code=404, detail="Parish not found")
        return ParishResponse.from_summary(p)

    @app.get("/v1/parishes/{parish_id}/bulletins/current",
             response_model=Bulletin, tags=["bulletins"])
    def get_current_bulletin(
        parish_id: str,
        request: Request,
        response: Response,
        repo: Repository = Depends(get_repo),
    ) -> Bulletin:
        p = repo.get_parish(parish_id)
        if not p:
            raise HTTPException(status_code=404, detail="Parish not found")
        rec = repo.get_current_bulletin(parish_id)
        if not rec:
            raise HTTPException(status_code=404, detail="No bulletin available for this parish yet")
        etag = _etag_for(rec)
        if _check_not_modified(request, etag):
            return Response(status_code=304, headers=_bulletin_cache_headers(rec))  # type: ignore[return-value]
        for k, v in _bulletin_cache_headers(rec).items():
            response.headers[k] = v
        return rec.bulletin

    @app.get("/v1/parishes/{parish_id}/bulletins/{week_starting}",
             response_model=Bulletin, tags=["bulletins"])
    def get_bulletin_by_date(
        parish_id: str,
        week_starting: date,
        request: Request,
        response: Response,
        repo: Repository = Depends(get_repo),
    ) -> Bulletin:
        p = repo.get_parish(parish_id)
        if not p:
            raise HTTPException(status_code=404, detail="Parish not found")
        rec = repo.get_bulletin_for_date(parish_id, week_starting)
        if not rec:
            raise HTTPException(
                status_code=404,
                detail=f"No bulletin found for week starting {week_starting.isoformat()}",
            )
        etag = _etag_for(rec)
        if _check_not_modified(request, etag):
            return Response(status_code=304, headers=_bulletin_cache_headers(rec))  # type: ignore[return-value]
        for k, v in _bulletin_cache_headers(rec).items():
            response.headers[k] = v
        return rec.bulletin

    @app.get("/v1/parishes/{parish_id}/today", response_model=TodayResponse, tags=["views"])
    def get_today(
        parish_id: str,
        response: Response,
        repo: Repository = Depends(get_repo),
    ) -> TodayResponse:
        p = repo.get_parish(parish_id)
        if not p:
            raise HTTPException(status_code=404, detail="Parish not found")
        rec = repo.get_current_bulletin(parish_id)
        if not rec:
            raise HTTPException(status_code=404, detail="No bulletin available")
        view = today_view(rec.bulletin, p.timezone)
        for k, v in _today_cache_headers().items():
            response.headers[k] = v
        return TodayResponse(
            parish_id=parish_id,
            as_of=view.as_of,
            today=view.today,
            next_service=DatedServiceResponse.from_dated(view.next_service)
                if view.next_service else None,
            today_services_remaining=[
                DatedServiceResponse.from_dated(s)
                for s in view.today_services_remaining
            ],
            this_week_exceptions=view.this_week_exceptions,
            high_priority_announcements=view.high_priority_announcements,
            todays_intentions=view.todays_intentions,
        )

    @app.get("/v1/parishes/{parish_id}/schedule",
             response_model=ScheduleResponse, tags=["views"])
    def get_schedule(
        parish_id: str,
        days: int = 7,
        response: Response = None,  # type: ignore[assignment]
        repo: Repository = Depends(get_repo),
    ) -> ScheduleResponse:
        if days < 1 or days > 31:
            raise HTTPException(status_code=400, detail="days must be 1..31")
        p = repo.get_parish(parish_id)
        if not p:
            raise HTTPException(status_code=404, detail="Parish not found")
        rec = repo.get_current_bulletin(parish_id)
        if not rec:
            raise HTTPException(status_code=404, detail="No bulletin available")
        services = schedule_view(rec.bulletin, p.timezone, days=days)
        if response is not None:
            for k, v in _today_cache_headers().items():
                response.headers[k] = v
        return ScheduleResponse(
            parish_id=parish_id,
            days=days,
            services=[DatedServiceResponse.from_dated(s) for s in services],
        )

    # Simple health endpoint for load balancers
    @app.get("/health", tags=["meta"])
    def health() -> dict[str, Any]:
        return {"ok": True}

    return app
