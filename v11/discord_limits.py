from __future__ import annotations

"""Defensive Discord embed pagination.

Discord rejects an entire webhook request when any embed/field exceeds its limits.
This layer keeps the analytical/reporting text intact by splitting oversized field
values and, when needed, sending a logical embed as several safe webhook messages.
It does not alter any model, selector, staking or recommendation decision.
"""

TITLE_LIMIT = 256
DESCRIPTION_LIMIT = 4096
FIELD_NAME_LIMIT = 256
FIELD_VALUE_LIMIT = 1024
FIELDS_PER_EMBED_LIMIT = 25
EMBED_TOTAL_LIMIT = 6000
# Leave a small margin for future Discord counting differences / continuation text.
EMBED_TOTAL_BUDGET = 5800

_INSTALLED = False


def _clip(text, limit):
    text = str(text or "")
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1].rstrip() + "…"


def _split_text(text, limit=FIELD_VALUE_LIMIT):
    """Split text without discarding content, preferring paragraph/line boundaries."""
    text = str(text or "—")
    if not text:
        text = "—"
    out = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[: limit + 1]
        cut = window.rfind("\n\n", 0, limit + 1)
        if cut < max(1, limit // 3):
            cut = window.rfind("\n", 0, limit + 1)
        if cut < max(1, limit // 3):
            cut = window.rfind(" ", 0, limit + 1)
        if cut < max(1, limit // 3):
            cut = limit
        chunk = remaining[:cut].rstrip()
        if not chunk:
            chunk = remaining[:limit]
            cut = len(chunk)
        out.append(chunk)
        remaining = remaining[cut:].lstrip("\n ")
    if remaining or not out:
        out.append(remaining or "—")
    return out


def _expanded_fields(fields):
    expanded = []
    for raw_name, raw_value in fields or []:
        name = _clip(raw_name or "—", FIELD_NAME_LIMIT)
        chunks = _split_text(raw_value, FIELD_VALUE_LIMIT)
        total = len(chunks)
        for idx, chunk in enumerate(chunks, 1):
            if idx == 1:
                part_name = name
            else:
                suffix = f" (suite {idx}/{total})"
                part_name = _clip(name, max(1, FIELD_NAME_LIMIT - len(suffix))) + suffix
            expanded.append((part_name, _clip(chunk or "—", FIELD_VALUE_LIMIT)))
    return expanded


def _embed_chars(title, description, fields):
    return len(title or "") + len(description or "") + sum(len(n) + len(v) for n, v in fields)


def build_pages(title, fields, color=5763719, description=None):
    """Return safe logical pages consumable by core.send_embed."""
    title = _clip(title or "—", TITLE_LIMIT)
    description = _clip(description, DESCRIPTION_LIMIT) if description else None
    expanded = _expanded_fields(fields)
    if not expanded:
        expanded = [("Info", "—")]

    pages = []
    current = []
    page_no = 1

    def page_title(number):
        if number == 1:
            return title
        suffix = f" • suite {number}"
        return _clip(title, max(1, TITLE_LIMIT - len(suffix))) + suffix

    for field in expanded:
        ptitle = page_title(page_no)
        pdesc = description if page_no == 1 else None
        candidate = current + [field]
        over_fields = len(candidate) > FIELDS_PER_EMBED_LIMIT
        over_chars = _embed_chars(ptitle, pdesc, candidate) > EMBED_TOTAL_BUDGET
        if current and (over_fields or over_chars):
            pages.append({"title": ptitle, "fields": current, "color": color, "description": pdesc})
            page_no += 1
            current = [field]
        else:
            current = candidate

    if current:
        ptitle = page_title(page_no)
        pdesc = description if page_no == 1 else None
        pages.append({"title": ptitle, "fields": current, "color": color, "description": pdesc})

    return pages


def validate_page(page):
    title = str(page.get("title") or "")
    description = str(page.get("description") or "")
    fields = page.get("fields") or []
    return (
        len(title) <= TITLE_LIMIT
        and len(description) <= DESCRIPTION_LIMIT
        and len(fields) <= FIELDS_PER_EMBED_LIMIT
        and all(len(str(n)) <= FIELD_NAME_LIMIT and len(str(v)) <= FIELD_VALUE_LIMIT for n, v in fields)
        and _embed_chars(title, description, fields) <= EMBED_TOTAL_LIMIT
    )


def install():
    global _INSTALLED
    if _INSTALLED:
        return True
    from . import core
    if getattr(core, "_discord_limits_installed", False):
        _INSTALLED = True
        return True

    original = core.send_embed

    def safe_send_embed(title, fields, color=5763719, description=None):
        pages = build_pages(title, fields, color=color, description=description)
        ok = True
        for page in pages:
            if not validate_page(page):
                core.logging.error("Discord preflight invalide malgré pagination: title=%r", page.get("title"))
                return False
            sent = original(
                page["title"], page["fields"], page["color"],
                description=page.get("description"),
            )
            ok = bool(sent) and ok
            if not sent:
                break
        return ok

    core.send_embed = safe_send_embed
    core._discord_limits_installed = True
    core._discord_original_send_embed = original
    _INSTALLED = True
    return True
