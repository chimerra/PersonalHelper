import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv
from pydantic import ValidationError

from app.schemas import AnalysisResult, StructuredAIResult

load_dotenv()

logger = logging.getLogger("app.ai")

DEFAULT_OPENAI_BASE_URL = "https://openai.api.proxyapi.ru/v1"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"

ACTION_VERBS = [
    "купить",
    "отправить",
    "позвонить",
    "оплатить",
    "подготовить",
    "создать",
    "сделать",
    "написать",
    "дописать",
    "доделать",
    "переделать",
    "переделыва",
    "прочитать",
    "уточнить",
    "созвон",
    "съездить",
    "сходить",
    "заехать",
    "забрать",
    "записаться",
    "заказать",
    "забронировать",
    "встретиться",
    "забыть",
]

TITLE_CONTEXT_HINTS: list[tuple[str, str]] = [
    (r"курсов", "к курсовой"),
    (r"диплом", "к диплому"),
    (r"отч[её]т", "к отчёту"),
    (r"реферат", "к реферату"),
    (r"эссе", "к эссе"),
    (r"пост", "к посту"),
    (r"стать", "к статье"),
    (r"письм", "к письму"),
    (r"презентац", "к презентации"),
    (r"хостинг|сайт", "по сайту"),
]

CONTEXT_SUFFIXES = {suffix.lower().replace("ё", "е") for _, suffix in TITLE_CONTEXT_HINTS}

NOTE_KEYWORDS = ["идея", "идею", "идеи", "наблюдение", "ссылка", "мысль", "черновик"]

# Канонический справочник тегов: канон -> ключевые подстроки (нижний регистр, ё→е).
TAG_KEYWORDS: dict[str, list[str]] = {
    "работа": [
        "работ", "начальник", "шеф", "босс", "коллег", "офис", "совещан",
        "планерк", "отчет", "клиент", "заказчик", "договор", "контракт",
        "реквизит", "проект", "задач по работе", "командировк", "резюме",
        "собеседован", "ваканс",
    ],
    "разработка": [
        "код", "баг", "багов", "девелоп", "программ", "деплой", "продакшен",
        "прод", "релиз", "сервер", "бэкенд", "фронтенд", "api", "апи", "фикс",
        "мердж", "коммит", "репозитор", "тест", "хостинг", "сайт", "приложен",
        "верстк", "база данных", "бд",
    ],
    "учеба": [
        "учеб", "универ", "школ", "лекци", "семинар", "экзам", "зачет",
        "сесси", "курсов", "диплом", "реферат", "конспект", "домашк",
        "пара", "студент", "контрольн", "практик",
    ],
    "финансы": [
        "деньг", "оплат", "счет", "кредит", "ипотек", "налог", "бюджет",
        "накоплен", "инвест", "банк", "перевод", "платеж", "долг", "зарплат",
        "аванс", "расход", "подписк",
    ],
    "здоровье": [
        "врач", "доктор", "больниц", "поликлин", "анализ", "таблетк",
        "лекарств", "зуб", "стоматолог", "терапевт", "давлен", "витамин",
        "прививк", "узи", "диспансер", "осмотр",
    ],
    "спорт": [
        "трениров", "зал", "фитнес", "бег", "йог", "пробежк", "вело",
        "плаван", "спорт", "качалк", "растяжк",
    ],
    "дом": [
        "убор", "уборк", "квартир", "ремонт", "посуд", "стирк", "пылесос",
        "мусор", "коммунал", "жкх", "переезд", "мебел", "сантехник",
    ],
    "покупки": [
        "купить", "магазин", "заказ", "продукт", "маркет", "доставк",
        "корзин", "озон", "вайлдберриз", "wb", "купи",
    ],
    "еда": [
        "готов", "рецепт", "ужин", "обед", "завтрак", "еда", "кафе",
        "ресторан", "приготов", "меню",
    ],
    "семья": [
        "семь", "семей", "мам", "пап", "родител", "сестр", "брат",
        "бабушк", "дедушк", "дочк", "сын", "жена", "муж", "ребен",
        "дети", "детей", "тещ", "свекров",
    ],
    "друзья": ["друг", "подруг", "приятел", "тусовк", "вечеринк"],
    "путешествия": [
        "поездк", "путешеств", "отпуск", "билет", "отель", "виза",
        "чемодан", "аэропорт", "рейс", "бронир", "тур", "загранпаспорт",
    ],
    "праздники": [
        "подарок", "подарк", "праздник", "день рожден", "др ", "новый год",
        "юбилей", "поздрав", "8 марта", "23 феврал", "годовщин",
    ],
    "авто": [
        "машин", "авто", "заправк", "бензин", "шиномонтаж", "страховк",
        "осаго", "техосмотр", "колес",
    ],
    "питомцы": ["кот", "кош", "собак", "пес", "ветеринар", "корм", "питом", "щенок"],
    "природа": ["природ", "дача", "шашлык", "пикник", "лес", "парк", "рыбалк", "поход"],
    "встречи": ["встреч", "созвон", "митинг", "переговор", "свидан"],
    "звонки": ["позвон", "звонок", "перезвон", "набрать"],
    "документы": [
        "документ", "паспорт", "справк", "нотариус", "мфц", "госуслуг",
        "заявлен", "анкет", "оформ",
    ],
    "контент": [
        "пост", "стать", "блог", "ролик", "видео", "промпт", "сценар",
        "канал", "рилс", "сторис", "монтаж",
    ],
    "идея": ["иде", "мысл", "придума", "концепц", "задумк"],
    "отдых": ["отдых", "отдохн", "выходн", "релакс", "прогулк", "погуля"],
    "развлечения": ["фильм", "сериал", "кино", "игр", "концерт", "театр", "книг", "музык"],
    "личное": ["личн", "кофе", "устал", "хобби", "саморазвит", "медитац"],
}

# Синонимы/варианты -> канон (после нормализации: lower, ё→е, схлоп пробелов).
TAG_SYNONYMS: dict[str, str] = {
    "work": "работа",
    "рабочее": "работа",
    "дела": "работа",
    "job": "работа",
    "study": "учеба",
    "учёба": "учеба",
    "code": "разработка",
    "coding": "разработка",
    "код": "разработка",
    "программирование": "разработка",
    "девелопмент": "разработка",
    "dev": "разработка",
    "баг": "разработка",
    "багфикс": "разработка",
    "health": "здоровье",
    "sport": "спорт",
    "фитнес": "спорт",
    "home": "дом",
    "house": "дом",
    "shopping": "покупки",
    "покупка": "покупки",
    "food": "еда",
    "family": "семья",
    "friends": "друзья",
    "travel": "путешествия",
    "trip": "путешествия",
    "отпуск": "путешествия",
    "finance": "финансы",
    "money": "финансы",
    "деньги": "финансы",
    "docs": "документы",
    "док": "документы",
    "документ": "документы",
    "idea": "идея",
    "идеи": "идея",
    "мысль": "идея",
    "personal": "личное",
    "call": "звонки",
    "звонок": "звонки",
    "meeting": "встречи",
    "встреча": "встречи",
    "подарок": "праздники",
    "подарки": "праздники",
    "праздник": "праздники",
    "pet": "питомцы",
    "питомец": "питомцы",
    "car": "авто",
    "машина": "авто",
}


URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"']+", re.IGNORECASE)


def extract_urls(text: str) -> list[str]:
    """Return URLs found in the text, trimming trailing punctuation."""
    urls: list[str] = []
    for raw in URL_RE.findall(text or ""):
        cleaned = raw.rstrip(".,;:!?)»\"'")
        if cleaned and cleaned not in urls:
            urls.append(cleaned)
    return urls


def _context_words(text: str, url: str) -> set[str]:
    idx = text.find(url)
    if idx < 0:
        return set()
    window = text[max(0, idx - 80): idx]
    return set(re.findall(r"[а-яёa-z0-9]{3,}", window.lower().replace("ё", "е")))


def _item_words(item: "StructuredAIResult") -> set[str]:
    blob = f"{item.title} {item.description}".lower().replace("ё", "е")
    return set(re.findall(r"[а-яёa-z0-9]{3,}", blob))


def assign_urls(items: list["StructuredAIResult"], text: str) -> dict[int, list[str]]:
    """Map URLs missing from items to the most relevant item index by context."""
    assignment: dict[int, list[str]] = {i: [] for i in range(len(items))}
    if not items:
        return assignment
    for url in extract_urls(text):
        already = any(
            url in (it.description or "") or url in (it.title or "") for it in items
        )
        if already:
            continue
        ctx = _context_words(text, url)
        best_i, best_score = 0, -1.0
        for i, it in enumerate(items):
            score = float(len(ctx & _item_words(it)))
            if it.item_type == "note":
                score += 0.5
            if score > best_score:
                best_score, best_i = score, i
        assignment[best_i].append(url)
    return assignment


def normalize_tag_name(name: str) -> str:
    n = name.lower().strip().replace("ё", "е")
    return re.sub(r"\s+", " ", n)


def canonical_tag(name: str) -> str:
    """Map a tag to its canonical form via synonyms; keep new tags as-is."""
    n = normalize_tag_name(name)
    return TAG_SYNONYMS.get(n, n)


def _keyword_hits(low: str, keyword: str) -> bool:
    """Match a stem keyword only at a word boundary to avoid mid-word matches."""
    pattern = r"(?<![а-яa-z0-9])" + re.escape(keyword)
    return re.search(pattern, low) is not None


def guess_tags(text: str) -> list[str]:
    """Keyword-based tags from the canonical vocabulary (word-boundary aware)."""
    low = text.lower().replace("ё", "е")
    tags: list[str] = []
    for canon, keywords in TAG_KEYWORDS.items():
        if canon in tags:
            continue
        if any(_keyword_hits(low, kw) for kw in keywords):
            tags.append(canon)
    return tags[:5]


def finalize_tags(ai_tags: list[str] | None, text: str) -> list[str]:
    """Prefer model tags (canonicalised); fall back to keyword guess; guarantee >=1."""
    result: list[str] = []
    for raw in ai_tags or []:
        if not raw or not str(raw).strip():
            continue
        canon = canonical_tag(str(raw))
        if canon and canon not in result:
            result.append(canon)
    if not result:
        result = guess_tags(text)
    if not result:
        result.append("общее")
    return result[:5]


def tag_reference(known_tags: list[str] | None = None) -> str:
    """Build the tag vocabulary string for the prompt."""
    vocab = list(TAG_KEYWORDS.keys())
    for t in known_tags or []:
        c = canonical_tag(t)
        if c and c not in vocab:
            vocab.append(c)
    return ", ".join(vocab)

HIGH_PRIORITY_KEYWORDS = ["срочно", "важно", "критично", "иначе", "дедлайн"]

TOO_GENERAL_PHRASES = [
    "сделай важное",
    "потом разберусь",
    "разберись",
    "что-нибудь",
]

SYSTEM_PROMPT = """Ты модуль структурирования текста для персонального помощника.
Твоя задача — преобразовать входной текст в строгий JSON.
Не добавляй объяснения.
Не используй markdown.
Не используй ```json.
Верни только валидный JSON.

Схема:
{
  "item_type": "task" | "note",
  "title": string,
  "due_date": string | null,
  "priority": "low" | "medium" | "high",
  "tags": string[],
  "confidence": "high" | "medium" | "low",
  "needs_review": boolean
}

Правила:
- task: если в тексте есть конкретное действие: купить, отправить, позвонить, оплатить, подготовить, создать, сделать.
- note: если текст содержит идею, наблюдение, ссылку, мысль или информацию без конкретного действия.
- Если текст слишком общий, противоречивый или неясный, поставь confidence="low" и needs_review=true.
- Если несколько разных намерений в одном тексте, поставь needs_review=true.
- Не выдумывай срок. Если срок не указан явно, due_date=null.
- Если срок словами и ты не уверен, due_date=null и needs_review=true.
- Приоритет high ставь для слов: срочно, важно, критично, иначе сайт ляжет, дедлайн.
- Если приоритет не указан, ставь medium.
- Теги должны быть короткими, 1–2 слова, на русском языке.
- title — КРАТКИЙ заголовок с глаголом и объектом, до 60 символов. Примеры: «Дописать введение к курсовой», «Переделать отчёт». НЕ пиши только «к курсовой» или «к отчёту» — это не заголовок.
- Если в тексте несколько дел, выбери главное действие с ближайшим дедлайном и поставь needs_review=true.
- Полный исходный текст сохраняется отдельно; в title только формулировка действия.
- Для note с меткой до двоеточия (идея, мысль, прикольная мысль) title = краткая суть ПОСЛЕ двоеточия.
- Для note с описательным заголовком («Идея для поста: …») title = часть ДО двоеточия."""


ANALYZE_PROMPT = """Ты — модуль разбора потока мыслей в задачи и заметки.
Пользователь надиктовывает поток сознания. Выдели из него ОТДЕЛЬНЫЕ конкретные дела и осмысленные мысли.

Верни СТРОГО валидный JSON без markdown и пояснений:
{{
  "items": [
    {{
      "item_type": "task" | "note",
      "title": "краткий заголовок до 60 символов; для задачи начинай с глагола",
      "description": "развёрнутая формулировка своими словами, или \\"\\" если добавить нечего",
      "due_date": "YYYY-MM-DD" | null,
      "priority": "low" | "medium" | "high",
      "tags": ["короткие", "теги"],
      "needs_review": true | false,
      "review_reason": "коротко почему неясно" | null
    }}
  ],
  "ignored": "перечисли отброшенный мусор/эмоции, или \\"\\""
}}

Правила:
- Каждое отдельное дело или мысль = отдельный объект в items. Если в тексте три дела — верни три объекта.
- task — есть конкретное действие (купить, съездить, доделать, позвонить, записаться…). note — мысль/идея/наблюдение/информация без действия.
- title — краткий и по сути. description — подробнее, но без воды. НЕ копируй весь исходный текст в title.
- ВАЖНО: сохраняй ДОСЛОВНО ссылки (http/https/www), цитаты, числа, имена, адреса, артикулы — их нельзя перефразировать или выбрасывать. Если в мысли есть ссылка — обязательно включи её целиком в description.
- Отбрасывай мусор: эмоции, вводные слова («слушай», «думаю», «блин», «а то совсем забила»), погодные ремарки и прочее, что не несёт дела или полезной мысли. Перечисли отброшенное в "ignored".
- needs_review=true ставь ТОЛЬКО если непонятно, что конкретно за дело, или срок размытый и важный. Если дело понятное — needs_review=false.
- due_date: только при явном сроке. «через неделю» = сегодня + 7 дней. «через N дней» = сегодня + N. «в выходные»/«на выходные» = ближайшая суббота. «завтра» = сегодня + 1. Если срока нет — null.
- priority high для слов: срочно, важно, критично, дедлайн.
- Теги: у каждого объекта ОБЯЗАТЕЛЬНО хотя бы один тег (1–2 слова, на русском, в нижнем регистре).
- Сначала переиспользуй подходящий тег из справочника ниже; новый короткий тег придумывай ТОЛЬКО если ни один из справочника не подходит.
- Справочник тегов: {tag_reference}.
- Не выдумывай факты, которых нет в тексте.
- Если в тексте нет ни дел, ни осмысленных мыслей — верни {{"items": [], "ignored": "..."}}.

{memory_instructions}{memory_block}
Сегодня: {today} ({weekday})."""


MEMORY_INSTRUCTIONS = """У тебя может быть блок «Контекст пользователя».
Используй его для выбора тегов, понимания общего контекста, формулировки названия и priority,
если в памяти явно указано правило (например: «тег работа = важное» → priority high для задачи с этим тегом).
Не выдумывай новые задачи, сроки, людей или детали на основе памяти.
Если входной текст неясен — ставь needs_review=true.

"""


def _memory_prompt_parts(memory_context: str | None) -> tuple[str, str]:
    block = (memory_context or "").strip()
    if not block:
        return "", ""
    return MEMORY_INSTRUCTIONS, f"\n{block}\n"


WEEKDAYS_RU = [
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
]

FILLER_PREFIXES = [
    "слушай",
    "короче",
    "блин",
    "кстати",
    "ну",
    "вот",
    "так",
    "значит",
    "в общем",
    "думаю",
    "может быть",
    "может",
    "наверное",
    "вроде",
    "надо не забыть",
    "не забыть",
    "надо бы",
    "надо",
    "нужно",
    "хочу",
    "хотел бы",
    "хотела бы",
    "а ещё",
    "а еще",
    "и ещё",
    "и еще",
    "ещё",
    "еще",
    "а",
    "и",
]

CONNECTIVE_SPLIT = re.compile(
    r"\s+(?:а\s+ещё|а\s+еще|и\s+ещё|и\s+еще|а\s+также|ещё\s+надо|еще\s+надо|"
    r"потом\s+надо|а\s+потом|также)\s+",
    re.IGNORECASE,
)


def _today() -> date:
    return date.today()


def _next_saturday(today: date) -> date:
    days_ahead = (5 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return today + timedelta(days=days_ahead)


def parse_due_phrase(text: str, today: date | None = None) -> str | None:
    """Best-effort parse of a relative deadline phrase into an ISO date."""
    today = today or _today()
    lower = text.lower().replace("ё", "е")

    m = re.search(r"через\s+(\d+)\s+(дн|день|дня|дней|недел)", lower)
    if m:
        n = int(m.group(1))
        if m.group(2).startswith("недел"):
            return (today + timedelta(weeks=n)).isoformat()
        return (today + timedelta(days=n)).isoformat()
    if "через неделю" in lower:
        return (today + timedelta(days=7)).isoformat()
    if "послезавтра" in lower:
        return (today + timedelta(days=2)).isoformat()
    if "завтра" in lower:
        return (today + timedelta(days=1)).isoformat()
    if "выходн" in lower:
        return _next_saturday(today).isoformat()
    if "сегодня" in lower and ("дедлайн" in lower or "срок" in lower or "сдать" in lower):
        return today.isoformat()
    return None


def _strip_filler(clause: str) -> str:
    cleaned = clause.strip().strip("…").strip()
    changed = True
    while changed:
        changed = False
        low = cleaned.lower()
        for word in FILLER_PREFIXES:
            if low.startswith(word + " ") or low == word:
                cleaned = cleaned[len(word):].lstrip(" ,.—-").strip()
                changed = True
                break
    # отбрасываем эмоциональный хвост вида «, а то совсем забила …»
    cleaned = re.split(r",?\s+а\s+то\b", cleaned, maxsplit=1, flags=re.IGNORECASE)[0]
    return cleaned.strip().strip(",").strip()


def _split_clauses(text: str) -> list[str]:
    raw_parts = re.split(r"[.!?…\n]+", text)
    clauses: list[str] = []
    for part in raw_parts:
        for chunk in CONNECTIVE_SPLIT.split(part):
            chunk = chunk.strip()
            if chunk:
                clauses.append(chunk)
    return clauses


def _is_meaningful_clause(clause: str) -> bool:
    low = clause.lower()
    if any(v in low for v in ACTION_VERBS):
        return True
    if any(k in low for k in NOTE_KEYWORDS) or "иде" in low:
        return True
    return False


def shorten_title(title: str, max_len: int = 60) -> str:
    cleaned = title.strip()
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 3] + "..."


def _is_weak_title(title: str) -> bool:
    """Title is too vague to show (e.g. AI returned only «к курсовой»)."""
    t = title.strip().lower().replace("ё", "е")
    if not t:
        return True
    if t in CONTEXT_SUFFIXES:
        return True
    if len(t) < 18 and re.fullmatch(r"(к|по|для|в|на|о)\s+[\w\-]+", t):
        return True
    return False


def _title_has_context(title: str) -> bool:
    lower = title.lower().replace("ё", "е")
    if _is_weak_title(title):
        return False
    return bool(re.search(r"\b(к|для|по)\s+[\w\-]+", lower))


def enrich_title_with_context(title: str, raw_text: str) -> str:
    """Add object from raw text when title lacks context («дописать введение» → «… к курсовой»)."""
    title = title.strip()
    if not title:
        return title
    if _title_has_context(title):
        return shorten_title(title)

    lower_text = raw_text.lower().replace("ё", "е")
    lower_title = title.lower().replace("ё", "е")
    for pattern, suffix in TITLE_CONTEXT_HINTS:
        if re.search(pattern, lower_text) and not re.search(pattern, lower_title):
            enriched = shorten_title(f"{title} {suffix}")
            if not _is_weak_title(enriched):
                return enriched
    return shorten_title(title)


def resolve_title(item_type: str, ai_title: str | None, raw_text: str) -> str:
    """Pick a good title: trust AI unless it's vague, then extract from raw text."""
    candidate = (ai_title or "").strip()
    if _is_weak_title(candidate):
        candidate = (
            _extract_task_title(raw_text)
            if item_type == "task"
            else _extract_note_title(raw_text)
        )
    if _is_weak_title(candidate):
        candidate = _extract_title(raw_text)
    return enrich_title_with_context(candidate, raw_text)


def finalize_title(title: str, raw_text: str) -> str:
    if _is_weak_title(title):
        return resolve_title("task", title, raw_text)
    return enrich_title_with_context(title, raw_text)


def _extract_title(text: str, max_len: int = 60) -> str:
    return shorten_title(text.strip(), max_len)


def _is_meta_note_prefix(prefix: str) -> bool:
    """True if prefix is a label like «прикольная мысль», not a topic title."""
    p = prefix.strip().lower().replace("ё", "е")
    exact = {
        "идея",
        "мысль",
        "наблюдение",
        "черновик",
        "ссылка",
        "заметка",
        "прикольная мысль",
        "интересная мысль",
    }
    if p in exact:
        return True
    if re.search(r"\b(для|про|о)\b", p):
        return False
    if len(p) <= 25 and re.search(r"(^|\s)(мысль|идея|наблюдение|черновик|ссылка)$", p):
        return True
    return False


def _clean_note_body_title(body: str, max_len: int = 120) -> str:
    """Extract the core idea from text after a meta prefix."""
    body = body.strip()
    for sep in [" - ", ", типа", ", вот ", ". "]:
        if sep in body:
            first = body.split(sep, 1)[0].strip().rstrip(",")
            if len(first) >= 10:
                body = first
                break
    if "," in body:
        first, rest = body.split(",", 1)
        first = first.strip()
        if len(first) >= 15 and any(
            w in rest.lower() for w in ("типа", "вот", "такая", "получилось", "текста")
        ):
            body = first
    if len(body) > max_len:
        body = body[: max_len - 3] + "..."
    return body


def _extract_note_title(text: str) -> str:
    if ":" not in text:
        return _extract_title(text)
    prefix, body = text.split(":", 1)
    prefix = prefix.strip()
    body = body.strip()
    if _is_meta_note_prefix(prefix):
        return _clean_note_body_title(body)
    if len(prefix) <= 40:
        return prefix
    return _extract_title(text)


def normalize_note_result(text: str, result: StructuredAIResult) -> StructuredAIResult:
    """Heuristic note cleanup — only for fallback, not when AI already processed."""
    if result.processed_by_ai or result.item_type != "note":
        return result
    extracted = _extract_note_title(text)
    if extracted:
        result.title = resolve_title("note", extracted, text)
    return result


def note_fields_for_storage(raw_text: str, structured: StructuredAIResult) -> tuple[str, str]:
    """Return (title, text) for note storage. text is always the full original input."""
    text = raw_text.strip()
    if structured.item_type != "note":
        return resolve_title(structured.item_type, structured.title, text), text

    title = structured.title.strip()
    if not structured.processed_by_ai:
        if ":" in raw_text and _is_meta_note_prefix(raw_text.split(":", 1)[0]):
            title = title or _clean_note_body_title(raw_text.split(":", 1)[1])
        elif ":" in raw_text:
            prefix = raw_text.split(":", 1)[0].strip()
            if not _is_meta_note_prefix(prefix) and len(prefix) <= 40:
                title = title or prefix
            else:
                title = title or _extract_note_title(text)
        else:
            title = title or _extract_note_title(text)

    return resolve_title("note", title, text), text


def _extract_task_title(text: str) -> str:
    """Pick the sentence with an action verb for task title."""
    lower = text.lower()
    parts = re.split(r"[.!?…]", text)
    for part in reversed(parts):
        part_lower = part.lower()
        if any(verb in part_lower for verb in ACTION_VERBS):
            cleaned = part.strip()
            cleaned = re.sub(r"^(ну|и|а|но)\s+", "", cleaned, flags=re.I)
            while True:
                shortened = re.sub(r"^(надо|нужно|срочно)\s+", "", cleaned, flags=re.I)
                if shortened == cleaned:
                    break
                cleaned = shortened
            if len(cleaned) >= 8:
                return shorten_title(cleaned)
    for verb in ACTION_VERBS:
        if verb in lower:
            idx = lower.index(verb)
            snippet = text[max(0, idx - 20) : idx + 40].strip(" ,.")
            if len(snippet) >= 8:
                return shorten_title(snippet)
    return _extract_title(text)


def _detect_multiple_intents(text: str) -> bool:
    lower = text.lower()
    has_task = any(v in lower for v in ACTION_VERBS)
    has_payment = any(w in lower for w in ["оплат", "подпис", "разобра"])
    has_note = any(k in lower for k in NOTE_KEYWORDS) or "иде" in lower or "пост" in lower
    if "иде" in lower and (has_task or has_payment):
        return True
    if len(text) > 100 and has_note and has_payment:
        return True
    if len(text) > 120 and has_note and (has_task or has_payment):
        return True
    if lower.count(".") >= 2 and has_note and has_payment:
        return True
    if ("…" in text or "..." in lower) and has_note and has_payment:
        return True
    if len(text) > 100 and has_note and has_task:
        return True
    work_topics = sum(
        1 for p in (r"отч", r"курсов", r"диплом", r"хостинг", r"сайт", r"пост")
        if re.search(p, lower)
    )
    if work_topics >= 2 and has_task:
        return True
    return False


def _is_too_general(text: str) -> bool:
    lower = text.lower().strip()
    for phrase in TOO_GENERAL_PHRASES:
        if phrase in lower:
            return True
    if len(lower) < 15 and not any(v in lower for v in ACTION_VERBS + NOTE_KEYWORDS):
        return True
    return False


def _guess_tags(text: str) -> list[str]:
    """Backward-compatible helper: keyword guess with «общее» fallback."""
    tags = guess_tags(text)
    return tags or ["общее"]


def _clean_description(clause: str, title: str) -> str:
    body = clause.strip().strip(",").strip()
    if not body:
        return ""
    if body.lower().replace("ё", "е") == title.lower().replace("ё", "е"):
        return ""
    return body


def _review_note(text: str, reason: str = "UNSTRUCTURED") -> StructuredAIResult:
    return StructuredAIResult(
        item_type="note",
        title=resolve_title("note", None, text),
        description="",
        due_date=None,
        priority="medium",
        tags=_guess_tags(text),
        confidence="low",
        needs_review=True,
        review_reason=reason,
        processed_by_ai=False,
    )


def _build_item_from_clause(clause: str, today: date) -> StructuredAIResult | None:
    cleaned = _strip_filler(clause)
    if len(cleaned) < 4:
        return None
    low = cleaned.lower()
    is_task = any(v in low for v in ACTION_VERBS)
    is_note_kw = any(k in low for k in NOTE_KEYWORDS) or "иде" in low
    if not is_task and not is_note_kw:
        return None

    item_type = "task" if is_task else "note"
    due = parse_due_phrase(clause, today) if item_type == "task" else None
    priority = "high" if any(k in low for k in HIGH_PRIORITY_KEYWORDS) else "medium"
    title = resolve_title(item_type, None, cleaned)
    description = _clean_description(cleaned, title)

    return StructuredAIResult(
        item_type=item_type,
        title=title,
        description=description,
        due_date=due,
        priority=priority,
        tags=_guess_tags(cleaned),
        confidence="medium",
        needs_review=False,
        processed_by_ai=False,
    )


def analyze_text_fallback(text: str, reason: str = "no API key") -> AnalysisResult:
    preview = text.strip().replace("\n", " ")[:60]
    logger.info("[AI] local fallback multi (%s): %s...", reason, preview)
    today = _today()

    items: list[StructuredAIResult] = []
    ignored_parts: list[str] = []
    for clause in _split_clauses(text):
        item = _build_item_from_clause(clause, today)
        if item is not None:
            items.append(item)
        else:
            leftover = _strip_filler(clause)
            if leftover:
                ignored_parts.append(leftover)

    if not items:
        return AnalysisResult(
            items=[_review_note(text)],
            ignored=None,
            processed_by_ai=False,
        )

    return AnalysisResult(
        items=items,
        ignored="; ".join(ignored_parts) or None,
        processed_by_ai=False,
    )


def _valid_iso_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


def _item_from_ai_dict(d: dict, raw_text: str, today: date) -> StructuredAIResult | None:
    if not isinstance(d, dict):
        return None

    title = str(d.get("title") or "").strip()
    description = str(d.get("description") or "").strip()

    item_type = d.get("item_type")
    if item_type not in ("task", "note"):
        base = f"{title} {description}".lower()
        item_type = "task" if any(v in base for v in ACTION_VERBS) else "note"

    priority = d.get("priority")
    if priority not in ("low", "medium", "high"):
        priority = "medium"

    raw_tags = d.get("tags") or []
    tags = [str(t).strip() for t in raw_tags if str(t).strip()][:5] if isinstance(raw_tags, list) else []

    needs_review = bool(d.get("needs_review"))
    review_reason = d.get("review_reason") or None

    due = d.get("due_date")
    if due is not None:
        due = str(due).strip() or None
    if due and not _valid_iso_date(due):
        due = parse_due_phrase(f"{title} {description} {raw_text}", today)

    if _is_weak_title(title):
        title = resolve_title(item_type, title, description or raw_text)
        if _is_weak_title(title):
            needs_review = True
            review_reason = review_reason or "LOW_CONFIDENCE"
    else:
        title = shorten_title(title)

    if not title:
        return None

    return StructuredAIResult(
        item_type=item_type,  # type: ignore[arg-type]
        title=title,
        description=description,
        due_date=due,
        priority=priority,  # type: ignore[arg-type]
        tags=tags,
        confidence="high",
        needs_review=needs_review,
        review_reason=review_reason,
        processed_by_ai=True,
    )


async def analyze_text_with_openai(
    text: str,
    known_tags: list[str] | None = None,
    memory_context: str | None = None,
) -> AnalysisResult:
    from openai import AsyncOpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL)
    model = os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
    today = _today()

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    logger.info(
        "[AI] ProxyAPI request: model=%s, base_url=%s, text_len=%d",
        model,
        base_url,
        len(text),
    )
    mem_instr, mem_block = _memory_prompt_parts(memory_context)
    prompt = ANALYZE_PROMPT.format(
        today=today.isoformat(),
        weekday=WEEKDAYS_RU[today.weekday()],
        tag_reference=tag_reference(known_tags),
        memory_instructions=mem_instr,
        memory_block=mem_block,
    )
    response = await client.chat.completions.create(
        model=model,
        temperature=0.1,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Текст: {text}"},
        ],
    )
    raw = response.choices[0].message.content or ""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("[AI] invalid JSON from model, switching to local fallback")
        return analyze_text_fallback(text, reason="invalid JSON from model")

    if isinstance(data, dict):
        items_data = data.get("items", [])
        ignored = data.get("ignored") or None
    elif isinstance(data, list):
        items_data = data
        ignored = None
    else:
        items_data, ignored = [], None

    items: list[StructuredAIResult] = []
    for d in items_data if isinstance(items_data, list) else []:
        item = _item_from_ai_dict(d, text, today)
        if item is not None:
            items.append(item)

    if not items:
        logger.info("[AI] ProxyAPI ok: nothing actionable, storing review note")
        return AnalysisResult(items=[_review_note(text)], ignored=ignored, processed_by_ai=True)

    logger.info(
        "[AI] ProxyAPI ok: items=%d (%s), ignored=%r",
        len(items),
        ", ".join(f"{i.item_type}:{i.title[:30]}" for i in items),
        (ignored or "")[:80],
    )
    return AnalysisResult(items=items, ignored=ignored, processed_by_ai=True)


async def analyze_text(
    text: str,
    known_tags: list[str] | None = None,
    memory_context: str | None = None,
) -> AnalysisResult:
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key and api_key.strip():
        try:
            return await analyze_text_with_openai(text, known_tags, memory_context)
        except Exception as exc:
            logger.exception("[AI] ProxyAPI error, switching to local fallback: %s", exc)
            return analyze_text_fallback(text, reason=f"API error: {exc}")
    return analyze_text_fallback(text, reason="OPENAI_API_KEY not set")
