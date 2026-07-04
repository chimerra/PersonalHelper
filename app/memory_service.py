"""User memory: extract stable facts, store, and inject context for AI structuring."""

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import MemoryFact

MEMORY_CATEGORIES = frozenset(
    {"preference", "context", "habit", "project", "person", "other"}
)

PREFERENCE_MARKERS_HIGH = [
    r"\bобычно\b",
    r"\bчаще\s+всего\b",
    r"\bмне\s+удобнее\b",
    r"\bя\s+предпочитаю\b",
    r"\bпо\s+умолчанию\b",
    r"\bвсегда\s+став[ьи]\b",
    r"\bдля\s+таких\s+задач\s+используй\b",
    r"\bдля\s+.+\s+обычно\s+используй\b",
    r"\bведу\s+с\s+тегом\b",
    r"\bиспользую\s+тег\b",
]

PREFERENCE_MARKERS_MEDIUM = [
    r"\bнаверное\b",
    r"\bможет\s+быть\b",
    r"\bскорее\s+всего\b",
]

EMOTION_PATTERNS = [
    r"\bустал\b",
    r"\bблин\b",
    r"\bдень\s+сумасшедш",
    r"\bпочему\s+вс[ёе]\b",
    r"\bненавиж\b",
    r"\bобидн\b",
    r"\bзлюсь\b",
    r"\bдепресс\b",
]

SENSITIVE_PATTERNS = [
    r"\bпаспорт\b",
    r"\bинн\b",
    r"\bснилс\b",
    r"\bкредитн",
    r"\bдиагноз\b",
    r"\bлечен\b",
    r"\bполитик\b",
    r"\bрелиги\b",
    r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
]

ONE_TIME_PATTERNS = [
    r"\bсегодня\b",
    r"\bзавтра\b",
    r"\bпослезавтра\b",
    r"\bчерез\s+\d+\s+(?:дн|час)",
    r"\bкупить\b",
    r"\bотправить\b",
    r"\bпозвонить\b",
    r"\bоплатить\b",
    r"\bсозвон\b",
    r"\bвстреч[аи]\b",
]

def _norm_ru(text: str) -> str:
    return text.replace("ё", "е").replace("Ё", "Е")


TAG_PREF_RE = re.compile(
    r"(?:для\s+)?(?P<context>[\w\s«»\"]{0,50}?)?(?:с\s+)?тег\w*\s+[«\"']?(\w+)[»\"']?",
    re.IGNORECASE,
)

TAG_PRIORITY_RE = re.compile(
    r"тег\w*\s+[«\"']?(\w+)[»\"']?",
    re.IGNORECASE,
)

PRIORITY_SIGNAL_RE = re.compile(
    r"high|важн|срочн|высок\w*\s+приоритет|priority\s+high",
    re.IGNORECASE,
)

MEMORY_FILLER_RE = re.compile(
    r"(?:\s*[-—]\s*)?(?:подумай|запомни(?:\s+ли\s+это|\s+на\s+будущее)?|"
    r"это\s+не\s+про\s+одну\s+задачу|просто\s+привычка).*$",
    re.IGNORECASE,
)

PRIORITY_PREF_RE = re.compile(
    r"(?:срочн\w*\s+задач\w*|приоритет\w*).*?(high|low|medium|высок\w*|низк\w*|средн\w*)",
    re.IGNORECASE,
)

STYLE_PREF_RE = re.compile(
    r"(?:я\s+)?(?:предпочитаю|удобнее[^.]{0,40}?)(?P<value>коротк\w*\s+назван\w*[^.]{0,80})",
    re.IGNORECASE,
)

PROJECT_RE = re.compile(
    r"(?:работаю\s+над|веду\s+проект|мой\s+проект)\s+(.{3,80}?)(?:\.|$)",
    re.IGNORECASE,
)

USER_ID_RE = re.compile(r"\buser_id\s+([a-zA-Z0-9_-]+)\b", re.IGNORECASE)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def memory_fact_to_dict(fact: MemoryFact) -> dict:
    return {
        "id": fact.id,
        "user_id": fact.user_id,
        "created_at": fact.created_at,
        "updated_at": fact.updated_at,
        "key": fact.key,
        "value": fact.value,
        "category": fact.category,
        "confidence": fact.confidence,
        "needs_review": fact.needs_review,
        "is_active": fact.is_active,
        "source_type": fact.source_type,
        "source_id": fact.source_id,
    }


def get_user_memory(
    db: Session,
    user_id: str,
    *,
    include_inactive: bool = False,
    needs_review: bool | None = None,
) -> list[MemoryFact]:
    q = db.query(MemoryFact).filter(MemoryFact.user_id == user_id)
    if not include_inactive:
        q = q.filter(MemoryFact.is_active.is_(True))
    if needs_review is not None:
        q = q.filter(MemoryFact.needs_review == needs_review)
    return q.order_by(MemoryFact.created_at.desc()).all()


def get_memory_fact(db: Session, memory_id: str, user_id: str) -> MemoryFact | None:
    return (
        db.query(MemoryFact)
        .filter(MemoryFact.id == memory_id, MemoryFact.user_id == user_id)
        .first()
    )


TAG_IN_MEMORY_RE = re.compile(
    r"тег\w*\s+[«\"']?(\w+)[»\"']?",
    re.IGNORECASE,
)

PRIORITY_BOOST_WORDS = [
    r"\bважн",
    r"\bhigh\b",
    r"\bсрочн",
    r"\bвысок\w*\s+приоритет",
    r"\bприоритет\s+high",
    r"\bпомечать\s+как\s+важ",
    r"\bкак\s+важн",
]

def _active_memory_facts(db: Session, user_id: str) -> list[MemoryFact]:
    return (
        db.query(MemoryFact)
        .filter(
            MemoryFact.user_id == user_id,
            MemoryFact.is_active.is_(True),
            MemoryFact.needs_review.is_(False),
        )
        .all()
    )


def resolve_priority_from_memory(
    priority: str,
    tags: list[str],
    user_id: str,
    db: Session,
) -> str:
    """Raise task priority to high when active memory links a tag to importance."""
    if priority == "high" or not tags:
        return priority

    tag_set = {t.lower().replace("ё", "е") for t in tags}
    for fact in _active_memory_facts(db, user_id):
        value = fact.value.lower().replace("ё", "е")
        if not _contains_pattern(value, PRIORITY_BOOST_WORDS):
            continue
        for match in TAG_IN_MEMORY_RE.finditer(value):
            mem_tag = match.group(1).lower().replace("ё", "е")
            if mem_tag in tag_set:
                return "high"
        for tag in tag_set:
            if len(tag) >= 3 and tag in value:
                return "high"
    return priority


def build_memory_context(user_id: str, db: Session) -> str:
    facts = (
        db.query(MemoryFact)
        .filter(
            MemoryFact.user_id == user_id,
            MemoryFact.is_active.is_(True),
            MemoryFact.needs_review.is_(False),
        )
        .order_by(MemoryFact.created_at.asc())
        .all()
    )
    if not facts:
        return ""
    lines = ["Контекст пользователя:"]
    for fact in facts:
        lines.append(f"- {fact.key}: {fact.value}")
    return "\n".join(lines)


def _normalize_category(category: str) -> str:
    cat = (category or "other").strip().lower()
    return cat if cat in MEMORY_CATEGORIES else "other"


def _duplicate_fact(db: Session, user_id: str, key: str, value: str) -> bool:
    return (
        db.query(MemoryFact)
        .filter(
            MemoryFact.user_id == user_id,
            MemoryFact.key == key,
            MemoryFact.value == value,
        )
        .first()
        is not None
    )


def _contains_pattern(text: str, patterns: list[str]) -> bool:
    lower = text.lower().replace("ё", "е")
    return any(re.search(p, lower, re.IGNORECASE) for p in patterns)


def _has_preference_marker(text: str) -> tuple[str, bool]:
    """Return (confidence, has_marker)."""
    if _contains_pattern(text, PREFERENCE_MARKERS_HIGH):
        return "high", True
    if _contains_pattern(text, PREFERENCE_MARKERS_MEDIUM):
        return "medium", True
    return "low", False


def _uncertain_preference(text: str) -> bool:
    return _contains_pattern(text, PREFERENCE_MARKERS_MEDIUM)


def _clean_preference_clause(clause: str) -> str:
    cleaned = MEMORY_FILLER_RE.sub("", clause).strip(" ,.—")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:200]


def _skip_reason(candidate: dict, source_text: str) -> str | None:
    key = (candidate.get("key") or "").strip()
    value = (candidate.get("value") or "").strip()
    if not key:
        return "empty_key"
    if not value:
        return "empty_value"
    if len(value) < 3:
        return "value_too_short"

    combined = f"{source_text} {value}".lower().replace("ё", "е")
    if _contains_pattern(combined, EMOTION_PATTERNS):
        return "emotion"
    if _contains_pattern(combined, SENSITIVE_PATTERNS):
        return "sensitive"

    conf, has_pref = _has_preference_marker(source_text)
    if not has_pref and _contains_pattern(combined, ONE_TIME_PATTERNS):
        return "one_time_task"

    if candidate.get("confidence") == "low" and not has_pref:
        return "low_confidence"

    return None


def _infer_candidates_from_text(text: str) -> list[dict]:
    """Rule-based memory candidates (works without AI)."""
    text = _norm_ru(text.strip())
    if not text:
        return []

    confidence, has_marker = _has_preference_marker(text)
    if not has_marker:
        return []

    candidates: list[dict] = []

    tag_pri = TAG_PRIORITY_RE.search(text)
    if tag_pri:
        tag = tag_pri.group(1).strip().lower()
        window = text[tag_pri.start() : tag_pri.end() + 120]
        if PRIORITY_SIGNAL_RE.search(window):
            candidates.append(
                {
                    "key": f"priority_for_tag_{tag}",
                    "value": f"тег {tag} → high priority",
                    "category": "preference",
                    "confidence": confidence,
                    "needs_review": _uncertain_preference(text) or confidence != "high",
                }
            )

    m = TAG_PREF_RE.search(text)
    if m and not any(c["key"].startswith("priority_for_tag_") for c in candidates):
        tag = m.group(2).strip().lower()
        ctx = (m.group(1) or "").strip().lower()
        if "high" not in text.lower() and "важн" not in text.lower():
            key = "preferred_tag_for_study_projects" if "учеб" in ctx else "preferred_tags"
            candidates.append(
                {
                    "key": key,
                    "value": tag,
                    "category": "preference",
                    "confidence": confidence,
                    "needs_review": _uncertain_preference(text) or confidence != "high",
                }
            )

    m = STYLE_PREF_RE.search(text)
    if m:
        value = m.group("value").strip().rstrip(".")
        candidates.append(
            {
                "key": "preferred_task_style",
                "value": value,
                "category": "preference",
                "confidence": confidence,
                "needs_review": confidence != "high",
            }
        )

    m = PRIORITY_PREF_RE.search(text)
    if m:
        candidates.append(
            {
                "key": "priority_preference",
                "value": "срочные задачи помечать high",
                "category": "preference",
                "confidence": "medium" if confidence == "high" else "medium",
                "needs_review": True,
            }
        )

    m = PROJECT_RE.search(text)
    if m:
        candidates.append(
            {
                "key": "default_project_context",
                "value": m.group(1).strip(),
                "category": "project",
                "confidence": confidence,
                "needs_review": confidence != "high",
            }
        )

    m = USER_ID_RE.search(text)
    if m:
        candidates.append(
            {
                "key": "user_id",
                "value": m.group(1),
                "category": "context",
                "confidence": "high",
                "needs_review": False,
            }
        )

    if not candidates and has_marker:
        clause = text
        for pat in PREFERENCE_MARKERS_HIGH + PREFERENCE_MARKERS_MEDIUM:
            clause = re.sub(pat, "", clause, flags=re.IGNORECASE).strip(" ,.")
        clause = _clean_preference_clause(clause)
        if len(clause) >= 3 and not _contains_pattern(clause, ONE_TIME_PATTERNS):
            candidates.append(
                {
                    "key": "user_preference",
                    "value": clause,
                    "category": "preference",
                    "confidence": confidence,
                    "needs_review": _uncertain_preference(text) or confidence != "high",
                }
            )

    return candidates


def extract_memory_candidates(text: str, structured_result: dict) -> list[dict]:
    """Find potential memory facts from source text and capture result."""
    del structured_result  # reserved for future AI-assisted extraction
    return _infer_candidates_from_text(text)


def create_memory_fact(
    db: Session,
    user_id: str,
    key: str,
    value: str,
    category: str,
    confidence: str,
    source_type: str | None,
    source_id: str | None,
    needs_review: bool,
) -> MemoryFact:
    fact = MemoryFact(
        id=f"mem_{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        created_at=now_iso(),
        updated_at=None,
        key=key.strip(),
        value=value.strip(),
        category=_normalize_category(category),
        source_type=source_type,
        source_id=source_id,
        confidence=confidence if confidence in {"high", "medium", "low"} else "medium",
        needs_review=needs_review,
        is_active=True,
    )
    db.add(fact)
    db.flush()
    return fact


def patch_memory_fact(
    db: Session,
    memory_id: str,
    user_id: str,
    updates: dict,
) -> MemoryFact | None:
    fact = get_memory_fact(db, memory_id, user_id)
    if not fact:
        return None
    if "key" in updates and updates["key"] is not None:
        fact.key = updates["key"].strip()
    if "value" in updates and updates["value"] is not None:
        fact.value = updates["value"].strip()
    if "category" in updates and updates["category"] is not None:
        fact.category = _normalize_category(updates["category"])
    if "needs_review" in updates and updates["needs_review"] is not None:
        fact.needs_review = bool(updates["needs_review"])
    if "is_active" in updates and updates["is_active"] is not None:
        fact.is_active = bool(updates["is_active"])
    fact.updated_at = now_iso()
    db.flush()
    return fact


def deactivate_memory_fact(db: Session, memory_id: str, user_id: str) -> MemoryFact | None:
    fact = get_memory_fact(db, memory_id, user_id)
    if not fact:
        return None
    fact.is_active = False
    fact.updated_at = now_iso()
    db.flush()
    return fact


def delete_memory_fact(db: Session, memory_id: str, user_id: str) -> bool:
    fact = get_memory_fact(db, memory_id, user_id)
    if not fact:
        return False
    db.delete(fact)
    db.flush()
    return True


def persist_memory_candidates(
    db: Session,
    user_id: str,
    text: str,
    structured_result: dict,
    *,
    source_type: str = "capture",
    source_id: str | None = None,
) -> dict:
    """Extract, validate, and save memory facts. Returns stats for API/audit."""
    candidates = extract_memory_candidates(text, structured_result)
    created = 0
    review_count = 0
    skipped = 0
    saved_ids: list[str] = []

    for candidate in candidates:
        reason = _skip_reason(candidate, text)
        if reason:
            skipped += 1
            continue

        key = candidate["key"].strip()
        value = candidate["value"].strip()
        if _duplicate_fact(db, user_id, key, value):
            skipped += 1
            continue

        needs_review = bool(candidate.get("needs_review"))
        if candidate.get("confidence") == "high" and not needs_review:
            needs_review = False
        elif candidate.get("confidence") == "medium":
            needs_review = True

        fact = create_memory_fact(
            db,
            user_id=user_id,
            key=key,
            value=value,
            category=candidate.get("category", "preference"),
            confidence=candidate.get("confidence", "medium"),
            source_type=source_type,
            source_id=source_id,
            needs_review=needs_review,
        )
        created += 1
        if fact.needs_review:
            review_count += 1
        saved_ids.append(fact.id)

    return {
        "created": created,
        "needs_review": review_count,
        "skipped": skipped,
        "candidates": candidates,
        "memory_ids": saved_ids,
    }
