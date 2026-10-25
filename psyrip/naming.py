"""Dynamic-Naming-Engine: [artist]\\[album]\\[track] [title] inkl. programmierbarer Aktionen.

Syntax: ``[tag]`` ist ein Tag-Wert, ``[FUNC]arg,arg,...[]``
ist eine Aktion, die mit ``[]`` abgeschlossen wird. Aktionen lassen sich verschachteln.
Ein Komma innerhalb eines Arguments wird als ``<comma_>`` geschrieben.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field

# Maximale Argumentzahl; das letzte Argument darf Kommas enthalten.
_ARITY = {
    "right": 2, "grab": 3, "del": 3, "setlen": 4, "ifequals": 3, "if!equals": 3,
    "if": 5, "ifvalue": 3, "replace": 3, "word": 2, "group": 2, "split": 3,
    "maxlength": 2,
}
_BLOCK_FUNCS = {
    "ifcomp", "if!comp", "ifmulti", "if!multi", "upper", "lower", "trim",
    "trimfirstfolder", "trimlastfolder", "frontfolder", "backfolder",
    "multitag", "tag", "source_date", *_ARITY,
}
_BAD_CHARS = {"\\": "-", "/": "-", ":": "-", "*": "-", "?": "", '"': "'", "<": "(", ">": ")", "|": "-"}


@dataclass
class NamingContext:
    tags: dict[str, str] = field(default_factory=dict)
    multi_tags: dict[str, list[str]] = field(default_factory=dict)
    origpath: str = ""
    origfilename: str = ""
    origdrive: str = ""
    extension: str = ""
    compilation: bool = False
    disc: int = 1
    source_date: _dt.datetime | None = None
    extra: dict[str, str] = field(default_factory=dict)
    restricted: dict[str, str] | None = None  # überschreibt _BAD_CHARS

    def lookup(self, name: str) -> str:
        n = name.strip().lower()
        if n == "origpath":
            return self.origpath
        if n == "origfilename":
            return self.origfilename
        if n == "origdrive":
            return self.origdrive
        if n == "extension":
            return self.extension
        if n in self.extra:
            return self.extra[n]
        v = self.tags.get(n, "")
        if n == "track" and v:
            head = v.split("/")[0].strip()
            return head.zfill(2) if head.isdigit() else head
        if n == "disc" and v:
            return v.split("/")[0].strip()
        return v


_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def sanitize(value: str, restricted: dict[str, str] | None = None) -> str:
    """Macht einen Tag-Wert dateinamentauglich (Sonderzeichen, Steuerzeichen, reservierte Windows-Namen)."""
    table = restricted if restricted is not None else _BAD_CHARS
    out = "".join(table.get(c, c) for c in value if c >= " ")
    out = out.strip().rstrip(". ")
    if out.split(".")[0].lower() in _RESERVED:
        out = "_" + out
    return out


# ---- Parser ---------------------------------------------------------------

def _parse(s: str, pos: int, nested: bool):
    nodes: list = []
    lit: list[str] = []

    def flush():
        if lit:
            nodes.append(("lit", "".join(lit)))
            lit.clear()

    while pos < len(s):
        c = s[pos]
        if c == "[":
            if nested and s.startswith("[]", pos):
                flush()
                return nodes, pos + 2
            end = s.find("]", pos)
            if end == -1:
                lit.append(c)
                pos += 1
                continue
            name = s[pos + 1:end]
            if name.lower() in _BLOCK_FUNCS:
                flush()
                children, pos = _parse(s, end + 1, True)
                nodes.append(("fn", name.lower(), children))
            elif name == "":
                lit.append("[]")
                pos = end + 1
            else:
                flush()
                nodes.append(("tag", name))
                pos = end + 1
        else:
            lit.append(c)
            pos += 1
    flush()
    return nodes, pos


def _split_args(children: list, arity: int | None) -> list[list]:
    """Teilt Knotenliste an literalen Kommas in Argumente."""
    args: list[list] = [[]]
    for node in children:
        if node[0] != "lit":
            args[-1].append(node)
            continue
        text = node[1]
        while True:
            if arity is not None and len(args) >= arity:
                args[-1].append(("lit", text))
                break
            i = text.find(",")
            if i == -1:
                args[-1].append(("lit", text))
                break
            args[-1].append(("lit", text[:i]))
            args.append([])
            text = text[i + 1:]
    return args


# ---- Auswertung -----------------------------------------------------------

def _ev(nodes: list, ctx: NamingContext) -> str:
    return "".join(_ev1(n, ctx) for n in nodes)


def _arg(args: list[list], i: int, ctx: NamingContext) -> str:
    return _ev(args[i], ctx).replace("<comma_>", ",") if i < len(args) else ""


def _int(s: str, default: int = 0) -> int:
    try:
        return int(s.strip())
    except ValueError:
        return default


def _ev1(node, ctx: NamingContext) -> str:
    kind = node[0]
    if kind == "lit":
        return node[1]
    if kind == "tag":
        if node[1].strip().lower() in ("origpath", "origdrive"):
            return ctx.lookup(node[1])
        return sanitize(ctx.lookup(node[1]), ctx.restricted)
    name, children = node[1], node[2]
    arity = _ARITY.get(name)
    if name in ("ifcomp", "if!comp", "ifmulti", "if!multi"):
        cond = {"ifcomp": ctx.compilation, "if!comp": not ctx.compilation,
                "ifmulti": ctx.disc > 1, "if!multi": ctx.disc <= 1}[name]
        return _ev(children, ctx) if cond else ""
    if name in ("upper", "lower", "trim"):
        v = _ev(children, ctx)
        return v.upper() if name == "upper" else v.lower() if name == "lower" else v.strip()
    if name == "trimfirstfolder":
        v = _ev(children, ctx)
        parts = v.replace("/", "\\").split("\\")
        return "\\".join(parts[1:])
    if name == "trimlastfolder":
        v = _ev(children, ctx)
        parts = v.replace("/", "\\").rstrip("\\").split("\\")
        return "\\".join(parts[:-1])
    if name in ("frontfolder", "backfolder"):
        n = _int(_ev(children, ctx), 1)
        parts = [p for p in ctx.origpath.replace("/", "\\").split("\\") if p and not p.endswith(":")]
        try:
            return parts[n - 1] if name == "frontfolder" else parts[-n]
        except IndexError:
            return ""
    if name == "tag":
        return sanitize(ctx.lookup(_ev(children, ctx)), ctx.restricted)
    if name == "multitag":
        key = _ev(children, ctx).strip().lower()
        vals = ctx.multi_tags.get(key) or ([ctx.tags[key]] if ctx.tags.get(key) else [])
        return sanitize("; ".join(vals), ctx.restricted)
    if name == "source_date":
        fmt = _ev(children, ctx)
        d = ctx.source_date or _dt.datetime.now()
        mapping = [("yyyy", "%Y"), ("mm", "%m"), ("dd", "%d"), ("hh", "%H"), ("xx", "%M"), ("ss", "%S"), ("ms", "%f")]
        out = fmt
        for k, v in mapping:
            out = out.replace(k, v)
        return d.strftime(out)[: len(fmt) + 8]
    args = _split_args(children, arity)
    a = lambda i: _arg(args, i, ctx)  # noqa: E731
    if name == "right":
        return a(1)[-max(_int(a(0)), 0):] if _int(a(0)) > 0 else ""
    if name == "grab":
        s, frm, to = a(2), _int(a(0), 1), a(1).strip()
        return s[frm - 1:(_int(to) if to else len(s))]
    if name == "del":
        s, frm, to = a(2), _int(a(0), 1), a(1).strip()
        return s[:frm - 1] + s[(_int(to) if to else len(s)):]
    if name == "setlen":
        cnt, pre, post, s = _int(a(0)), a(1).strip(), a(2).strip(), a(3)
        if len(s) >= cnt:
            return s[:cnt]
        pad = cnt - len(s)
        if pre:
            return chr(_int(pre)) * pad + s
        return s + (chr(_int(post)) * pad if post else " " * pad)
    if name in ("ifequals", "if!equals"):
        same = ctx.lookup(a(0)).lower() == a(1).strip().lower()
        return a(2) if same == (name == "ifequals") else ""
    if name == "if":
        val, cond, match = a(0), a(1).strip().lower(), a(2)
        if cond == "=":
            ok = val.lower() == match.strip().lower()
        elif cond == "len<":
            ok = len(val) < _int(match)
        elif cond == "len>":
            ok = len(val) > _int(match)
        elif cond == "len=":
            ok = len(val) == _int(match)
        else:
            ok = False
        return a(3) if ok else a(4)
    if name == "ifvalue":
        return a(1) if ctx.lookup(a(0)) else a(2)
    if name == "maxlength":
        n = _int(a(0))
        return a(1)[:n] if n > 0 else a(1)
    if name == "replace":
        return a(2).replace(a(0), a(1)) if a(0) else a(2)
    if name == "word":
        return " ".join(a(0).split()[:_int(a(1))])
    if name == "group":
        s, n = a(1), max(_int(a(0), 1), 1)
        if not s or not s[0].isalpha():
            return "#"
        idx = (ord(s[0].lower()) - 97) // n
        lo = chr(97 + idx * n)
        hi = chr(min(97 + idx * n + n - 1, 122))
        return f"{lo}-{hi}"
    if name == "split":
        sep, s, pos = a(0) or ",", a(1), _int(a(2), 1)
        parts = s.split(sep)
        return parts[pos - 1] if 0 < pos <= len(parts) else ""
    return ""


def render(template: str, ctx: NamingContext) -> str:
    """Wertet das Namensschema aus. Mehrfache Pfadtrenner werden bereinigt."""
    nodes, _ = _parse(template, 0, False)
    out = _ev(nodes, ctx)
    out = re.sub(r"[\\/]+", r"\\", out)
    parts = [p.strip().rstrip(".") for p in out.split("\\")]
    return "\\".join(p for p in parts if p)


DEFAULT_RIP_NAMING = (
    "[IFVALUE]album artist,[album artist],[IFCOMP]Various Artists[][IF!COMP][artist][][]"
    "\\[album][IFMULTI], Disc [disc][]\\[track] [artist] - [title]"
)
