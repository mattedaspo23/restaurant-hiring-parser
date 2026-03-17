import logging
from typing import List

from backend.models import CandidateProfile, FilterConfig, ScoredCandidate

logger = logging.getLogger(__name__)


def _passes_hard_filters(candidate: CandidateProfile, config: FilterConfig) -> bool:
    if config.role and candidate.role.lower() != config.role.lower():
        return False

    if config.min_years_exp > 0 and candidate.years_of_experience < config.min_years_exp:
        return False

    if config.required_certs:
        candidate_certs_lower = [c.lower() for c in candidate.certifications]
        for req_cert in config.required_certs:
            if req_cert.lower() not in candidate_certs_lower:
                return False

    if config.availability:
        config_avail = config.availability.lower().replace(" ", "").replace("-", "")
        cand_avail = candidate.availability.lower().replace(" ", "").replace("-", "")
        if config_avail and cand_avail and config_avail != cand_avail:
            avail_aliases = {
                "tempopieno": "fulltime",
                "fulltime": "fulltime",
                "parttime": "parttime",
                "weekend": "weekends",
                "finesettimana": "weekends",
                "serale": "evenings",
                "sera": "evenings",
                "flessibile": "fulltime",
            }
            normalized_config = avail_aliases.get(config_avail, config_avail)
            normalized_cand = avail_aliases.get(cand_avail, cand_avail)
            if normalized_config != normalized_cand:
                return False

    if config.languages:
        candidate_langs_lower = [l.lower() for l in candidate.languages]
        has_at_least_one = any(
            lang.lower() in candidate_langs_lower for lang in config.languages
        )
        if not has_at_least_one:
            return False

    return True


def _compute_score(candidate: CandidateProfile, config: FilterConfig) -> tuple:
    score = 50.0
    strengths = []
    gaps = []

    extra_years = candidate.years_of_experience - config.min_years_exp
    if extra_years > 0:
        bonus = min(extra_years * 10, 30)
        score += bonus
        strengths.append(
            f"{candidate.years_of_experience:.0f} anni di esperienza "
            f"(+{extra_years:.0f} oltre il minimo)"
        )
    elif config.min_years_exp > 0:
        gaps.append(
            f"Esperienza sotto il minimo richiesto ({candidate.years_of_experience:.0f}/{config.min_years_exp:.0f} anni)"
        )

    if candidate.has_haccp:
        score += 15
        strengths.append("Certificazione HACCP presente")
    else:
        gaps.append("Manca certificazione HACCP")

    if config.languages and len(config.languages) > 1:
        candidate_langs_lower = [l.lower() for l in candidate.languages]
        matched_extra = 0
        for lang in config.languages[1:]:
            if lang.lower() in candidate_langs_lower:
                matched_extra += 1
                strengths.append(f"Lingua: {lang}")
            else:
                gaps.append(f"Lingua mancante: {lang}")
        score += matched_extra * 5

    if config.languages:
        first_lang = config.languages[0]
        if first_lang.lower() in [l.lower() for l in candidate.languages]:
            strengths.append(f"Lingua principale: {first_lang}")
        else:
            gaps.append(f"Lingua principale mancante: {first_lang}")

    if config.bonus_filters and config.bonus_filters.skills:
        candidate_skills_lower = [s.lower() for s in candidate.skills]
        weights = config.bonus_filters.weights
        for i, skill in enumerate(config.bonus_filters.skills):
            weight = weights[i] if i < len(weights) else 1.0
            if skill.lower() in candidate_skills_lower:
                bonus = 5 * weight
                score += bonus
                strengths.append(f"Competenza bonus: {skill}")
            else:
                gaps.append(f"Competenza mancante: {skill}")

    if config.required_certs:
        candidate_certs_lower = [c.lower() for c in candidate.certifications]
        for cert in config.required_certs:
            if cert.lower() in candidate_certs_lower:
                strengths.append(f"Certificazione: {cert}")

    score = max(0.0, min(100.0, score))

    return round(score, 1), strengths, gaps


def apply_filters(
    candidates: List[CandidateProfile], config: FilterConfig
) -> List[ScoredCandidate]:
    results = []

    for candidate in candidates:
        if not _passes_hard_filters(candidate, config):
            logger.debug("Candidate %s excluded by hard filters", candidate.name)
            continue

        score, strengths, gaps = _compute_score(candidate, config)

        results.append(
            ScoredCandidate(
                candidate=candidate,
                score=score,
                strengths=strengths,
                gaps=gaps,
            )
        )

    results.sort(key=lambda sc: sc.score, reverse=True)
    logger.info(
        "Filter applied: %d/%d candidates passed", len(results), len(candidates)
    )
    return results
