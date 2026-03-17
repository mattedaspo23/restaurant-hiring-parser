import logging
from typing import List, Tuple

from backend.models import CandidateProfile, FilterConfig, ScoredCandidate

logger = logging.getLogger(__name__)


def _passes_hard_filters(candidate: CandidateProfile, config: FilterConfig) -> bool:
    """Exclude candidates who fail mandatory criteria."""

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
        candidate_langs_lower = [lang.lower() for lang in candidate.languages]
        has_at_least_one = any(
            lang.lower() in candidate_langs_lower for lang in config.languages
        )
        if not has_at_least_one:
            return False

    return True


def _compute_score(
    candidate: CandidateProfile, config: FilterConfig
) -> Tuple[float, List[str], List[str]]:
    """
    Weighted scoring: Σ(wᵢ · mᵢ) normalized to 0-100.

    Each criterion has a max weight. The candidate earns points for matches
    and LOSES points for gaps. Final score is normalized so that a perfect
    candidate = 100 and the worst passing candidate > 0.

    Weight distribution (total max = 100):
      - Experience:        25 pts max
      - HACCP:             15 pts max
      - Languages:         15 pts max
      - Bonus skills:      25 pts max
      - Extra certs:       10 pts max
      - Availability fit:  10 pts max
    """
    earned = 0.0
    max_possible = 0.0
    strengths = []
    gaps = []

    # ── Experience (max 25 pts) ──────────────────────────────────────────
    MAX_EXP = 25.0
    max_possible += MAX_EXP
    if config.min_years_exp > 0:
        extra_years = candidate.years_of_experience - config.min_years_exp
        if extra_years >= 0:
            # Scale: 0 extra = 60% of max, each extra year adds proportionally, cap at 10+ extra
            ratio = min(extra_years / max(config.min_years_exp, 1), 2.0)
            earned_exp = MAX_EXP * (0.6 + 0.4 * min(ratio, 1.0))
            earned += earned_exp
            if extra_years > 0:
                strengths.append(
                    f"{candidate.years_of_experience:.0f} anni di esperienza "
                    f"(+{extra_years:.0f} oltre il minimo di {config.min_years_exp:.0f})"
                )
            else:
                strengths.append(
                    f"{candidate.years_of_experience:.0f} anni di esperienza (minimo soddisfatto)"
                )
        else:
            gaps.append(
                f"Esperienza insufficiente ({candidate.years_of_experience:.0f}/{config.min_years_exp:.0f} anni)"
            )
    else:
        # No min required — give full points proportional to experience
        earned += min(candidate.years_of_experience / 5.0, 1.0) * MAX_EXP
        if candidate.years_of_experience > 0:
            strengths.append(f"{candidate.years_of_experience:.0f} anni di esperienza")

    # ── HACCP certification (max 15 pts) ─────────────────────────────────
    MAX_HACCP = 15.0
    max_possible += MAX_HACCP
    if candidate.has_haccp:
        earned += MAX_HACCP
        strengths.append("Certificazione HACCP presente")
    else:
        gaps.append("Manca certificazione HACCP")

    # ── Languages (max 15 pts) ───────────────────────────────────────────
    MAX_LANG = 15.0
    if config.languages:
        max_possible += MAX_LANG
        candidate_langs_lower = [lang.lower() for lang in candidate.languages]
        matched_count = 0
        total_required = len(config.languages)

        for lang in config.languages:
            if lang.lower() in candidate_langs_lower:
                matched_count += 1
                strengths.append(f"Lingua: {lang}")
            else:
                gaps.append(f"Lingua mancante: {lang}")

        if total_required > 0:
            earned += MAX_LANG * (matched_count / total_required)

        # Bonus for extra languages not in config
        extra_langs = [
            lang for lang in candidate.languages
            if lang.lower() not in [cl.lower() for cl in config.languages]
        ]
        if extra_langs:
            strengths.append(f"Lingue extra: {', '.join(extra_langs)}")

    # ── Bonus skills (max 25 pts) ────────────────────────────────────────
    MAX_BONUS = 25.0
    if config.bonus_filters and config.bonus_filters.skills:
        max_possible += MAX_BONUS
        candidate_skills_lower = [s.lower() for s in candidate.skills]
        weights = config.bonus_filters.weights
        total_weight = 0.0
        earned_weight = 0.0

        for i, skill in enumerate(config.bonus_filters.skills):
            weight = weights[i] if i < len(weights) else 1.0
            total_weight += weight

            if skill.lower() in candidate_skills_lower:
                earned_weight += weight
                strengths.append(f"Competenza bonus: {skill} (peso {weight})")
            else:
                gaps.append(f"Competenza mancante: {skill}")

        if total_weight > 0:
            earned += MAX_BONUS * (earned_weight / total_weight)

    # ── Extra certifications beyond required (max 10 pts) ────────────────
    MAX_EXTRA_CERTS = 10.0
    max_possible += MAX_EXTRA_CERTS
    if config.required_certs:
        required_lower = [c.lower() for c in config.required_certs]
        candidate_certs_lower = [c.lower() for c in candidate.certifications]

        # Required certs (already passed hard filter, so all present)
        for cert in config.required_certs:
            strengths.append(f"Certificazione richiesta: {cert}")

        # Extra certs beyond required
        extra_certs = [
            c for c in candidate.certifications
            if c.lower() not in required_lower
        ]
        if extra_certs:
            earned += MAX_EXTRA_CERTS
            strengths.append(f"Certificazioni extra: {', '.join(extra_certs)}")
        else:
            earned += MAX_EXTRA_CERTS * 0.5  # Baseline for meeting requirements
    else:
        # No certs required — reward any certs
        if candidate.certifications:
            earned += MAX_EXTRA_CERTS
            strengths.append(f"Certificazioni: {', '.join(candidate.certifications)}")

    # ── Availability match (max 10 pts) ──────────────────────────────────
    MAX_AVAIL = 10.0
    max_possible += MAX_AVAIL
    if config.availability:
        # Already passed hard filter, so availability matches
        earned += MAX_AVAIL
        strengths.append(f"Disponibilità compatibile: {candidate.availability}")
    else:
        earned += MAX_AVAIL

    # ── Normalize to 0-100 ───────────────────────────────────────────────
    if max_possible > 0:
        score = round((earned / max_possible) * 100, 1)
    else:
        score = 50.0

    score = max(0.0, min(100.0, score))

    return score, strengths, gaps


def apply_filters(
    candidates: List[CandidateProfile], config: FilterConfig
) -> List[ScoredCandidate]:
    """Apply hard filters then soft scoring, return ranked list."""
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
