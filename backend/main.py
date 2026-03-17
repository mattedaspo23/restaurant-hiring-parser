import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.config import settings
from backend.db import supabase_client
from backend.filters.filter_engine import apply_filters
from backend.ingestion.cv_uploader import router as cv_router
from backend.ingestion.easyjob_html import fetch_easyjob_listings
from backend.ingestion.indeed_rss import fetch_indeed_listings
from backend.models import FilterConfig, ScoringRecord
from backend.parser.nlp_pipeline import parse_candidate

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Restaurant Hiring Parser",
    description="ATS tool for Italian restaurant hiring",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cv_router)


@app.on_event("startup")
async def startup():
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Upload directory ensured: %s", upload_dir)


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "environment": settings.ENVIRONMENT}


class IngestRequest(BaseModel):
    role: str = ""
    location: Optional[str] = "Italia"


class IngestEasyJobRequest(BaseModel):
    role: str = "ristorazione"


class ScoreRequest(BaseModel):
    config_id: str


@app.post("/api/ingest/indeed")
async def ingest_indeed(request: IngestRequest):
    listings = fetch_indeed_listings(role=request.role, location=request.location or "Italia")
    candidates_created = []

    for listing in listings:
        try:
            profile = parse_candidate(
                raw_text=listing["raw_text"],
                source="indeed",
                source_url=listing.get("url"),
            )
            candidate_id = supabase_client.upsert_candidate(profile)
            candidates_created.append(candidate_id)
        except Exception as e:
            logger.error("Failed to process Indeed listing: %s", e)

    return {
        "message": f"Processed {len(candidates_created)} Indeed listings",
        "candidates": candidates_created,
        "total_fetched": len(listings),
    }


@app.post("/api/ingest/easyjob")
async def ingest_easyjob(request: IngestEasyJobRequest):
    listings = fetch_easyjob_listings(role=request.role)
    candidates_created = []

    for listing in listings:
        try:
            profile = parse_candidate(
                raw_text=listing["raw_text"],
                source="easyjob",
                source_url=listing.get("url"),
            )
            candidate_id = supabase_client.upsert_candidate(profile)
            candidates_created.append(candidate_id)
        except Exception as e:
            logger.error("Failed to process EasyJob listing: %s", e)

    return {
        "message": f"Processed {len(candidates_created)} EasyJob listings",
        "candidates": candidates_created,
        "total_fetched": len(listings),
    }


@app.get("/api/candidates")
async def get_candidates(role: Optional[str] = None, source: Optional[str] = None):
    filters = {}
    if role:
        filters["role"] = role
    if source:
        filters["source"] = source
    candidates = supabase_client.get_candidates(filters if filters else None)
    return {"candidates": [c.model_dump() for c in candidates]}


@app.get("/api/candidates/{candidate_id}")
async def get_candidate(candidate_id: str):
    try:
        candidates = supabase_client.get_candidates()
        for c in candidates:
            if c.id == candidate_id:
                return {"candidate": c.model_dump()}
        raise HTTPException(status_code=404, detail="Candidate not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/filters")
async def get_filter_configs():
    configs = supabase_client.get_filter_configs()
    return {"configs": [c.model_dump() for c in configs]}


@app.post("/api/filters")
async def save_filter_config(config: FilterConfig):
    config_id = supabase_client.save_filter_config(config)
    return {"message": "Filter config saved", "config_id": config_id}


@app.get("/api/filters/{config_id}")
async def get_filter_config(config_id: str):
    try:
        config = supabase_client.get_filter_config(config_id)
        return {"config": config.model_dump()}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/score")
async def score_candidates(request: ScoreRequest):
    try:
        config = supabase_client.get_filter_config(request.config_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    candidates = supabase_client.get_candidates()
    scored = apply_filters(candidates, config)

    records_saved = []
    for sc in scored:
        record = ScoringRecord(
            candidate_id=sc.candidate.id or "",
            config_id=request.config_id,
            score=sc.score,
            strengths=sc.strengths,
            gaps=sc.gaps,
        )
        record_id = supabase_client.save_scoring_record(record)
        records_saved.append(record_id)

    return {
        "message": f"Scored {len(scored)} candidates",
        "results": [
            {
                "candidate_id": sc.candidate.id,
                "name": sc.candidate.name,
                "role": sc.candidate.role,
                "score": sc.score,
                "strengths": sc.strengths,
                "gaps": sc.gaps,
            }
            for sc in scored
        ],
        "records_saved": len(records_saved),
    }


@app.get("/api/scoring-history")
async def get_scoring_history(config_id: Optional[str] = None):
    history = supabase_client.get_scoring_history(config_id)
    return {"history": [h.model_dump() for h in history]}


@app.get("/api/analytics/sources")
async def analytics_sources():
    candidates = supabase_client.get_candidates()
    source_counts = {}
    for c in candidates:
        source_counts[c.source] = source_counts.get(c.source, 0) + 1
    return {"sources": source_counts, "total": len(candidates)}


@app.get("/api/analytics/trends")
async def analytics_trends():
    candidates = supabase_client.get_candidates()
    daily_counts = {}
    for c in candidates:
        if c.created_at:
            day = c.created_at.strftime("%Y-%m-%d")
        else:
            day = "unknown"
        daily_counts[day] = daily_counts.get(day, 0) + 1

    sorted_days = sorted(daily_counts.items(), key=lambda x: x[0])
    return {
        "trends": [{"date": d, "count": n} for d, n in sorted_days],
        "total": len(candidates),
    }
