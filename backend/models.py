from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class BonusFilters(BaseModel):
    skills: List[str] = []
    weights: List[float] = []


class CandidateProfile(BaseModel):
    id: Optional[str] = None
    name: str
    role: str  # cuoco, cameriere, barista, pizzaiolo
    years_of_experience: float
    skills: List[str]
    certifications: List[str]
    has_haccp: bool  # mandatory flag
    availability: str  # full-time, part-time, weekends, evenings
    languages: List[str]
    source: str  # "indeed", "easyjob", "cv_upload"
    source_url: Optional[str] = None
    raw_text: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    gender: Optional[str] = None  # "M", "F", or None (unknown)
    has_children: Optional[bool] = None  # True/False/None
    created_at: Optional[datetime] = None


class FilterConfig(BaseModel):
    id: Optional[str] = None
    name: str  # config name for saving
    role: str
    min_years_exp: float = 0
    required_certs: List[str] = []
    availability: str = ""
    languages: List[str] = []
    bonus_filters: Optional[BonusFilters] = None
    required_gender: Optional[str] = None  # "F" for cameriera, None = any
    exclude_has_children_evening: bool = False
    created_at: Optional[datetime] = None


class ScoredCandidate(BaseModel):
    candidate: CandidateProfile
    score: float  # 0-100
    strengths: List[str]
    gaps: List[str]


class ScoringRecord(BaseModel):
    id: Optional[str] = None
    candidate_id: str
    config_id: str
    score: float
    strengths: List[str]
    gaps: List[str]
    scored_at: Optional[datetime] = None
