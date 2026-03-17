import hashlib
import json
import logging
from typing import Dict, List, Optional

from supabase import Client, create_client

from backend.config import settings
from backend.models import CandidateProfile, FilterConfig, ScoringRecord

logger = logging.getLogger(__name__)

_client: Optional[Client] = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    return _client


def _hash_source(source_url: Optional[str], email: Optional[str]) -> str:
    key = source_url or email or ""
    return hashlib.sha256(key.encode()).hexdigest()


def upsert_candidate(profile: CandidateProfile) -> str:
    client = get_client()
    data = profile.model_dump(exclude={"id", "created_at"})
    data["source_hash"] = _hash_source(profile.source_url, profile.email)

    existing = (
        client.table("candidates")
        .select("id")
        .eq("source_hash", data["source_hash"])
        .execute()
    )

    if existing.data:
        candidate_id = existing.data[0]["id"]
        client.table("candidates").update(data).eq("id", candidate_id).execute()
        logger.info("Updated candidate %s", candidate_id)
        return candidate_id

    result = client.table("candidates").insert(data).execute()
    candidate_id = result.data[0]["id"]
    logger.info("Inserted candidate %s", candidate_id)
    return candidate_id


def get_candidates(filters: Optional[Dict] = None) -> List[CandidateProfile]:
    client = get_client()
    query = client.table("candidates").select("*")

    if filters:
        if filters.get("role"):
            query = query.eq("role", filters["role"])
        if filters.get("source"):
            query = query.eq("source", filters["source"])
        if filters.get("has_haccp") is not None:
            query = query.eq("has_haccp", filters["has_haccp"])

    result = query.order("created_at", desc=True).execute()
    candidates = []
    for row in result.data:
        # Graceful fallback for new columns that may not exist in DB yet
        row.setdefault("gender", None)
        row.setdefault("has_children", None)
        candidates.append(CandidateProfile(**row))
    return candidates


def save_filter_config(config: FilterConfig) -> str:
    client = get_client()
    data = config.model_dump(exclude={"id", "created_at"})
    if data.get("bonus_filters"):
        data["bonus_filters"] = json.loads(json.dumps(data["bonus_filters"]))

    if config.id:
        client.table("filter_configs").update(data).eq("id", config.id).execute()
        logger.info("Updated filter config %s", config.id)
        return config.id

    result = client.table("filter_configs").insert(data).execute()
    config_id = result.data[0]["id"]
    logger.info("Inserted filter config %s", config_id)
    return config_id


def _normalize_filter_row(row: dict) -> dict:
    """Add defaults for new columns that may not exist in DB yet."""
    row.setdefault("required_gender", None)
    row.setdefault("exclude_has_children_evening", False)
    return row


def get_filter_configs() -> List[FilterConfig]:
    client = get_client()
    result = (
        client.table("filter_configs")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return [FilterConfig(**_normalize_filter_row(row)) for row in result.data]


def get_filter_config(config_id: str) -> FilterConfig:
    client = get_client()
    result = (
        client.table("filter_configs").select("*").eq("id", config_id).execute()
    )
    if not result.data:
        raise ValueError(f"Filter config {config_id} not found")
    return FilterConfig(**_normalize_filter_row(result.data[0]))


def save_scoring_record(record: ScoringRecord) -> str:
    client = get_client()
    data = record.model_dump(exclude={"id", "scored_at"})
    result = client.table("scoring_history").insert(data).execute()
    record_id = result.data[0]["id"]
    logger.info("Inserted scoring record %s", record_id)
    return record_id


def get_scoring_history(config_id: Optional[str] = None) -> List[ScoringRecord]:
    client = get_client()
    query = client.table("scoring_history").select("*")
    if config_id:
        query = query.eq("config_id", config_id)
    result = query.order("scored_at", desc=True).execute()
    return [ScoringRecord(**row) for row in result.data]


def get_candidates_with_scores(config_id: str) -> List[dict]:
    client = get_client()
    scores = (
        client.table("scoring_history")
        .select("*")
        .eq("config_id", config_id)
        .order("score", desc=True)
        .execute()
    )

    results = []
    for score_row in scores.data:
        candidate = (
            client.table("candidates")
            .select("*")
            .eq("id", score_row["candidate_id"])
            .execute()
        )
        if candidate.data:
            cand_row = candidate.data[0]
            cand_row.setdefault("gender", None)
            cand_row.setdefault("has_children", None)
            results.append(
                {
                    "candidate": CandidateProfile(**cand_row).model_dump(),
                    "score": score_row["score"],
                    "strengths": score_row["strengths"],
                    "gaps": score_row["gaps"],
                }
            )
    return results
