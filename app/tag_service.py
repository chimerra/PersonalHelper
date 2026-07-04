import re
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Tag

SYNONYMS: dict[str, str] = {
    "work": "работа",
    "рабочее": "работа",
    "дела": "работа",
    "study": "учеба",
    "учеба": "учеба",
    "учёба": "учеба",
    "docs": "документы",
    "док": "документы",
    "документы": "документы",
}


def normalize_tag(name: str) -> str:
    """Normalize tag name: lower, strip, ё→е, collapse spaces, apply synonyms."""
    normalized = name.lower().strip()
    normalized = normalized.replace("ё", "е")
    normalized = re.sub(r"\s+", " ", normalized)
    return SYNONYMS.get(normalized, normalized)


def get_or_create_tag(db: Session, name: str, user_id: str) -> Tag:
    normalized = normalize_tag(name)
    if not normalized:
        raise ValueError("Empty tag name after normalization")

    tag = (
        db.query(Tag)
        .filter(Tag.user_id == user_id, Tag.normalized_name == normalized)
        .first()
    )
    if tag:
        return tag

    tag = Tag(
        id=f"tag_{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        name=name.strip(),
        normalized_name=normalized,
        is_active=True,
    )
    db.add(tag)
    db.flush()
    return tag


def link_tags_to_item(
    db: Session,
    tag_names: list[str],
    user_id: str,
    item_type: str,
    item_id: str,
) -> list[str]:
    """Create tags and item_tag links; returns list of normalized tag names."""
    from app.models import ItemTag

    result: list[str] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    for raw_name in tag_names:
        if not raw_name or not raw_name.strip():
            continue
        tag = get_or_create_tag(db, raw_name, user_id)
        existing = (
            db.query(ItemTag)
            .filter(
                ItemTag.item_type == item_type,
                ItemTag.item_id == item_id,
                ItemTag.tag_id == tag.id,
            )
            .first()
        )
        if not existing:
            db.add(
                ItemTag(
                    id=f"it_{uuid.uuid4().hex[:12]}",
                    tag_id=tag.id,
                    item_type=item_type,
                    item_id=item_id,
                    created_at=now,
                )
            )
        if tag.normalized_name not in result:
            result.append(tag.normalized_name)

    return result


def get_tags_for_item(db: Session, item_type: str, item_id: str) -> list[str]:
    from app.models import ItemTag

    rows = (
        db.query(Tag.normalized_name)
        .join(ItemTag, ItemTag.tag_id == Tag.id)
        .filter(ItemTag.item_type == item_type, ItemTag.item_id == item_id)
        .all()
    )
    return [r[0] for r in rows]
