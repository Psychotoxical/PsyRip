"""ID-Tag-Verarbeitung (DSP "ID Tag Processing" und Utility "ID Tag Update").

Reihenfolge: Map, Deletions, Manipulation, Additions.
"""
from __future__ import annotations

import re

_SMALL = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or", "the", "to", "vs", "with"}


def smart_capitalize(s: str) -> str:
    words = s.lower().split(" ")
    out = []
    for i, w in enumerate(words):
        out.append(w if (w in _SMALL and 0 < i < len(words) - 1) else w[:1].upper() + w[1:])
    return " ".join(out)


def _cap(s: str, mode: str) -> str:
    return {"upper": s.upper(), "lower": s.lower(), "smart": smart_capitalize(s),
            "first": s[:1].upper() + s[1:].lower()}.get(mode, s)


def _cond(tags: dict[str, str], expr: str, contains: bool) -> bool:
    key, _, val = expr.partition("=")
    cur = tags.get(key.strip().lower(), "")
    val = val.strip()
    if val == "[anyvalue]":
        return cur != ""
    return (val.lower() in cur.lower()) if contains else (cur.lower() == val.lower())


def _subst(val: str, tags: dict[str, str]) -> str:
    return re.sub(r"\[([^\]]+)\]", lambda m: tags.get(m.group(1).strip().lower(), m.group(0)), val)


def apply_rules(tags: dict[str, str], rules: str) -> None:
    """``SET a=b IF c=d`` / ``SET a=b IFCONTAINS c=d`` oder zweizeilig ``IF c=d`` + ``SET a=b``."""
    pending: tuple[str, bool] | None = None
    for raw in rules.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"(?i)^SET\s+(.+?)=(.*?)(?:\s+(IFCONTAINS|IF)\s+(.+))?$", line)
        if m:
            key, val, kw, cond = m.group(1).strip().lower(), m.group(2), m.group(3), m.group(4)
            ok = True
            if kw:
                ok = _cond(tags, cond, kw.upper() == "IFCONTAINS")
            elif pending is not None:
                ok = _cond(tags, pending[0], pending[1])
            if ok:
                tags[key] = _subst(val.strip(), tags)
            continue
        m = re.match(r"(?i)^(IFCONTAINS|IF)\s+(.+)$", line)
        if m:
            pending = (m.group(2), m.group(1).upper() == "IFCONTAINS")


def apply_replacements(tags: dict[str, str], table: str) -> None:
    """Je Eintrag drei Zeilen: Suchtext[nocase], Ersatz, ``remove`` (optional) – oder ``a=>b`` pro Zeile."""
    pairs: list[tuple[str, str, bool]] = []
    for line in table.splitlines():
        if "=>" in line:
            a, b = line.split("=>", 1)
            nocase = a.endswith("[nocase]")
            pairs.append((a.removesuffix("[nocase]"), b, nocase))
    for k, v in list(tags.items()):
        for a, b, nocase in pairs:
            v = re.sub(re.escape(a), b.replace("\\", "\\\\"), v, flags=re.I if nocase else 0)
        tags[k] = v


def process(tags: dict[str, str], s: dict) -> dict[str, str]:
    t = {k.lower(): v for k, v in tags.items()}
    # 1. Map
    for line in s.get("map", "").splitlines():
        if ">" in line:
            a, b = (x.strip().lower() for x in line.split(">", 1))
            if a in t:
                t[b] = t[a]
    # 2. Deletions
    mode = s.get("delete_mode", "none")
    names = [x.strip().lower() for x in s.get("delete_names", "").split(";") if x.strip()]
    if mode == "all":
        t.clear()
    elif mode == "except":
        t = {k: v for k, v in t.items() if k in names}
    elif mode == "single":
        for n in names:
            t.pop(n, None)
    # 3. Manipulation
    cap = s.get("capitalize", "none")
    if cap != "none":
        for k in ("artist", "album", "title", "albumartist", "genre", "composer"):
            if k in t:
                t[k] = _cap(t[k], cap)
    if s.get("rules"):
        apply_rules(t, s["rules"])
    if s.get("replace"):
        apply_replacements(t, s["replace"])
    if s.get("multi_artist_to_semicolon"):
        for k in ("artist", "albumartist"):
            if k in t:
                t[k] = "; ".join(x.strip() for x in re.split(r"\s*[;/]\s*", t[k]) if x.strip())
    if s.get("drop_year_month_day") and "date" in t:
        t["date"] = t["date"][:4]
    if s.get("drop_track_count") and "tracknumber" in t:
        t["tracknumber"] = t["tracknumber"].split("/")[0]
    if s.get("drop_disc_count") and "discnumber" in t:
        t["discnumber"] = t["discnumber"].split("/")[0]
    if s.get("feat_to_title") and "artist" in t and ";" in t["artist"]:
        first, *rest = [x.strip() for x in t["artist"].split(";")]
        t["artist"] = first
        t["title"] = f"{t.get('title', '')} (feat. {', '.join(rest)})"
    # 4. Additions
    for line in s.get("additions", "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            t[k.strip().lower()] = _subst(v.strip(), t)
    return t
