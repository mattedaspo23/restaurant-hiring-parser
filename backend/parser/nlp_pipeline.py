import json
import logging
import re
from typing import List, Optional

import spacy
from openai import OpenAI

from backend.config import settings
from backend.models import CandidateProfile

logger = logging.getLogger(__name__)

KNOWN_ROLES = [
    "cuoco",
    "cameriere",
    "cameriera",
    "barista",
    "pizzaiolo",
    "pizzaiola",
    "cuoca",
    "lavapiatti",
    "sommelier",
    "maitre",
    "maître",
    "pasticcere",
    "chef",
    "aiuto cuoco",
    "capo partita",
    "responsabile di sala",
]

ROLE_GENDER_MAP = {
    "cameriera": "F",
    "cuoca": "F",
    "pizzaiola": "F",
    "barista": None,
    "cameriere": "M",
    "cuoco": "M",
    "pizzaiolo": "M",
}

GENDER_KEYWORDS_F = ["donna", "femmina", "sig.ra", "signora"]
GENDER_KEYWORDS_M = ["uomo", "maschio"]

CHILDREN_KEYWORDS = [
    "figli", "figlio", "figlia", "bambino", "bambina",
    "genitore", "madre", "padre", "mamma", "papà",
]

KNOWN_SKILLS = [
    "cucina italiana",
    "cucina internazionale",
    "pasticceria",
    "panificazione",
    "mixology",
    "cocktail",
    "caffetteria",
    "latte art",
    "servizio al tavolo",
    "gestione sala",
    "forno a legna",
    "impasto napoletano",
    "sushi",
    "griglia",
    "sommelier",
    "cantina",
    "vini",
    "mise en place",
    "cassa",
    "gestione ordini",
    "food cost",
    "haccp",
    "magazzino",
    "inventario",
    "primi piatti",
    "secondi piatti",
    "antipasti",
    "dolci",
    "catering",
    "banchetti",
    "buffet",
    "lievitazione",
    "impasto",
    "pizza",
    "forno",
]

KNOWN_CERTS = [
    "haccp",
    "sab",
    "alimentarista",
    "blsd",
    "rec",
    "attestato alimentarista",
    "certificazione haccp",
]

AVAILABILITY_MAP = {
    "tempo pieno": "full-time",
    "full time": "full-time",
    "full-time": "full-time",
    "part time": "part-time",
    "part-time": "part-time",
    "mezza giornata": "part-time",
    "weekend": "weekends",
    "fine settimana": "weekends",
    "sabato e domenica": "weekends",
    "serale": "evenings",
    "sera": "evenings",
    "turno serale": "evenings",
    "turni": "full-time",
    "flessibile": "full-time",
    "disponibilità immediata": "full-time",
}

KNOWN_LANGUAGES = [
    "italiano",
    "inglese",
    "francese",
    "spagnolo",
    "tedesco",
    "cinese",
    "arabo",
    "portoghese",
    "rumeno",
    "russo",
    "giapponese",
    "polacco",
    "albanese",
]

_nlp = None


def _get_nlp():
    global _nlp
    if _nlp is None:
        try:
            _nlp = spacy.load("it_core_news_sm")
        except OSError:
            logger.warning("spaCy it_core_news_sm not found, attempting it_core_news_lg")
            try:
                _nlp = spacy.load("it_core_news_lg")
            except OSError:
                logger.error("No Italian spaCy model found. Install with: python -m spacy download it_core_news_sm")
                _nlp = spacy.blank("it")
    return _nlp


def _extract_name_spacy(doc) -> Optional[str]:
    for ent in doc.ents:
        if ent.label_ == "PER":
            name = ent.text.strip()
            if len(name.split()) >= 2:
                return name
    return None


def _extract_role(text: str) -> Optional[str]:
    text_lower = text.lower()
    for role in KNOWN_ROLES:
        pattern = r"\b" + re.escape(role) + r"\b"
        if re.search(pattern, text_lower):
            return role
    return None


def _extract_years_experience(text: str) -> Optional[float]:
    patterns = [
        r"(\d+(?:[.,]\d+)?)\s*anni?\s*(?:di\s+)?esperienza",
        r"esperienza\s*(?:di\s+)?(\d+(?:[.,]\d+)?)\s*anni?",
        r"(\d+(?:[.,]\d+)?)\s*anni?\s*(?:nel\s+settore|in\s+ristorazione|come)",
        r"esperienza\s*(?:di\s+)?(\d+(?:[.,]\d+)?)\s*(?:anno|mesi)",
        r"(\d+)\+?\s*(?:years?|anni?)\s*(?:of\s+)?(?:experience|esperienza)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            val = match.group(1).replace(",", ".")
            return float(val)
    return None


def _extract_skills(text: str) -> List[str]:
    text_lower = text.lower()
    found = []
    for skill in KNOWN_SKILLS:
        if skill in text_lower and skill not in found:
            found.append(skill)
    return found


def _extract_certifications(text: str) -> List[str]:
    text_lower = text.lower()
    found = []
    for cert in KNOWN_CERTS:
        if cert in text_lower:
            normalized = cert.upper() if cert in ("haccp", "sab", "blsd", "rec") else cert.title()
            if normalized not in found:
                found.append(normalized)
    return found


def _extract_availability(text: str) -> Optional[str]:
    text_lower = text.lower()
    for keyword, value in AVAILABILITY_MAP.items():
        if keyword in text_lower:
            return value
    return None


def _extract_languages(text: str, doc) -> List[str]:
    text_lower = text.lower()
    found = []
    for lang in KNOWN_LANGUAGES:
        if lang in text_lower and lang.capitalize() not in found:
            found.append(lang.capitalize())

    for ent in doc.ents:
        if ent.label_ in ("MISC", "LOC"):
            ent_lower = ent.text.lower()
            for lang in KNOWN_LANGUAGES:
                if lang in ent_lower and lang.capitalize() not in found:
                    found.append(lang.capitalize())

    return found


def _extract_gender(text: str, role: Optional[str]) -> Optional[str]:
    if role and role in ROLE_GENDER_MAP:
        gender = ROLE_GENDER_MAP[role]
        if gender is not None:
            return gender

    text_lower = text.lower()
    for kw in GENDER_KEYWORDS_F:
        if kw in text_lower:
            return "F"
    for kw in GENDER_KEYWORDS_M:
        if kw in text_lower:
            return "M"
    return None


def _extract_has_children(text: str) -> Optional[bool]:
    text_lower = text.lower()
    for kw in CHILDREN_KEYWORDS:
        pattern = r"\b" + re.escape(kw) + r"\b"
        if re.search(pattern, text_lower):
            return True
    return None


def _extract_email(text: str) -> Optional[str]:
    match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
    return match.group(0) if match else None


def _extract_phone(text: str) -> Optional[str]:
    match = re.search(r"(?:\+?\d{1,3}[\s.-]?)?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}", text)
    return match.group(0).strip() if match else None


def _openai_fallback(raw_text: str) -> dict:
    if not settings.OPENAI_API_KEY:
        logger.warning("No OpenAI API key configured, skipping fallback")
        return {}

    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        prompt = (
            "Extract the following from this CV/job listing text. "
            "Return ONLY valid JSON with these keys: "
            "name (string), role (string, one of: cuoco, cuoca, cameriere, cameriera, barista, pizzaiolo, "
            "pizzaiola, lavapiatti, sommelier, maitre, pasticcere), "
            "years_of_experience (float), skills (list of strings), "
            "certifications (list of strings), availability (string: full-time, part-time, weekends, evenings), "
            "languages (list of strings), email (string or null), phone (string or null), "
            "gender (string: 'M', 'F', or null - infer from role name or context), "
            "has_children (boolean or null - true if text mentions children/kids/family with children).\n\n"
            f"Text:\n{raw_text[:4000]}"
        )

        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1000,
        )

        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        return json.loads(content)
    except Exception as e:
        logger.error("OpenAI fallback failed: %s", e)
        return {}


def parse_candidate(
    raw_text: str, source: str, source_url: str = None
) -> CandidateProfile:
    nlp = _get_nlp()
    doc = nlp(raw_text[:100000])

    name = _extract_name_spacy(doc)
    role = _extract_role(raw_text)
    years_exp = _extract_years_experience(raw_text)
    skills = _extract_skills(raw_text)
    certs = _extract_certifications(raw_text)
    availability = _extract_availability(raw_text)
    languages = _extract_languages(raw_text, doc)
    email = _extract_email(raw_text)
    phone = _extract_phone(raw_text)
    gender = _extract_gender(raw_text, role)
    has_children = _extract_has_children(raw_text)

    needs_fallback = (
        name is None
        or role is None
        or years_exp is None
        or not skills
        or availability is None
    )

    if needs_fallback:
        logger.info("spaCy extraction incomplete, calling OpenAI fallback")
        ai_result = _openai_fallback(raw_text)

        if not name and ai_result.get("name"):
            name = ai_result["name"]
        if not role and ai_result.get("role"):
            role = ai_result["role"]
        if years_exp is None and ai_result.get("years_of_experience") is not None:
            years_exp = float(ai_result["years_of_experience"])
        if not skills and ai_result.get("skills"):
            skills = ai_result["skills"]
        if not certs and ai_result.get("certifications"):
            certs = ai_result["certifications"]
        if not availability and ai_result.get("availability"):
            availability = ai_result["availability"]
        if not languages and ai_result.get("languages"):
            languages = ai_result["languages"]
        if not email and ai_result.get("email"):
            email = ai_result["email"]
        if not phone and ai_result.get("phone"):
            phone = ai_result["phone"]
        if gender is None and ai_result.get("gender"):
            gender = ai_result["gender"]
        if has_children is None and ai_result.get("has_children") is not None:
            has_children = ai_result["has_children"]

    has_haccp = any("haccp" in c.lower() for c in (certs or []))

    return CandidateProfile(
        name=name or "Sconosciuto",
        role=role or "non specificato",
        years_of_experience=years_exp or 0.0,
        skills=skills or [],
        certifications=certs or [],
        has_haccp=has_haccp,
        availability=availability or "non specificato",
        languages=languages or [],
        source=source,
        source_url=source_url,
        raw_text=raw_text,
        email=email,
        phone=phone,
        gender=gender,
        has_children=has_children,
    )
