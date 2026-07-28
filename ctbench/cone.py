"""Cone-of-influence analysis over a synthesisable Verilog-2001 subset.

The whole of ctbench's reference verdict rests on one question: *does the fan-in
cone of the completion signal contain a secret operand bit?*

A design is constant-time with respect to an observation signal when the value of
that signal at every cycle is a function of non-secret state alone.  A sound and
cheap over-approximation is the syntactic fan-in cone: if no secret input reaches
the observation signal through any assignment or through any condition guarding an
assignment, the signal cannot depend on a secret.  The cone over-approximates, so a
CONSTANT_TIME verdict is conservative; a LEAKY verdict names the reaching signals so
a human can confirm it.

Guard conditions are the part naive implementations miss.  In

    if (xr != yr) running <= 1'b0;

`running` does not syntactically receive `xr` or `yr`, but its value depends on both.
Every enclosing `if`/`case` condition is therefore an edge into every target assigned
beneath it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Verilog keywords and directives that must never be mistaken for signals.
_KEYWORDS = frozenset(["module", "endmodule", "input", "output", "inout", "wire", "reg", "integer", "parameter", "localparam", "assign", "always", "initial", "begin", "end", "if", "else", "case", "casez", "casex", "endcase", "default", "for", "while", "repeat", "posedge", "negedge", "or", "and", "not", "xor", "nand", "nor", "xnor", "buf", "bufif0", "bufif1", "notif0", "notif1", "function", "endfunction", "task", "endtask", "generate", "endgenerate", "genvar", "signed", "unsigned", "real", "time", "realtime", "event", "supply0", "supply1", "tri", "triand", "trior", "wand", "wor", "tri0", "tri1", "specify", "endspecify", "defparam", "disable", "force", "release", "fork", "join", "edge", "highz0", "highz1", "pulldown", "pullup", "rcmos", "rtran", "rtranif0", "rtranif1", "cmos", "nmos", "pmos", "rnmos", "rpmos", "tran", "tranif0", "tranif1", "vectored", "scalared", "small", "medium", "large", "strong0", "strong1", "weak0", "weak1"])

_IDENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_$]*)\b")
_SIZED_LITERAL = re.compile(r"\b\d+\s*'\s*[bBoOdDhH][0-9a-fA-FxXzZ_]+")
_BASED_LITERAL = re.compile(r"'\s*[bBoOdDhH][0-9a-fA-FxXzZ_]+")


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", " ", src)
    return src


def identifiers(expr: str) -> set[str]:
    """Signal names in an expression, with literals and keywords removed."""
    expr = _SIZED_LITERAL.sub(" ", expr)
    expr = _BASED_LITERAL.sub(" ", expr)
    return {m.group(1) for m in _IDENT.finditer(expr) if m.group(1) not in _KEYWORDS}


@dataclass
class Module:
    name: str
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    # target signal -> set of signals it depends on (assignment RHS + guards)
    deps: dict[str, set[str]] = field(default_factory=dict)

    def add(self, target: str, sources: set[str]) -> None:
        self.deps.setdefault(target, set()).update(sources - {target})

    def cone(self, roots: list[str]) -> set[str]:
        """Transitive fan-in closure of `roots`, inclusive of the roots."""
        seen: set[str] = set()
        stack = [r for r in roots]
        while stack:
            s = stack.pop()
            if s in seen:
                continue
            seen.add(s)
            stack.extend(self.deps.get(s, ()))
        return seen


_DIRECTIONS = ("input", "output", "inout")


def _declared(body: str, kw: str) -> list[str]:
    """Names declared with `kw`, handling both ANSI and non-ANSI port styles.

    A single declaration may name several signals (`input clk, rst, start;`) and
    may carry a width (`input [W-1:0] x, y;`), so the whole comma list is consumed
    up to the terminator or the next direction keyword rather than stopping at the
    first comma.
    """
    names: list[str] = []
    for m in re.finditer(rf"\b{kw}\b", body):
        i, n = m.end(), len(body)
        while i < n:
            # skip whitespace, net/variable types, signedness and width ranges
            m2 = re.match(r"\s*(?:wire|reg|logic|signed|unsigned)\b", body[i:])
            if m2:
                i += m2.end()
                continue
            m2 = re.match(r"\s*\[[^\]]*\]", body[i:])
            if m2:
                i += m2.end()
                continue
            break
        while i < n:
            m2 = re.match(r"\s*([A-Za-z_][A-Za-z0-9_$]*)", body[i:])
            if not m2:
                break
            nm = m2.group(1)
            if nm in _DIRECTIONS or nm in _KEYWORDS:
                break
            names.append(nm)
            i += m2.end()
            # an unpacked-array suffix or a following comma continues the list
            m3 = re.match(r"\s*\[[^\]]*\]", body[i:])
            if m3:
                i += m3.end()
            m3 = re.match(r"\s*,", body[i:])
            if not m3:
                break
            i += m3.end()
            m3 = re.match(r"\s*\[[^\]]*\]", body[i:])
            if m3:
                i += m3.end()
    return list(dict.fromkeys(names))


def _split_statements(block: str) -> list[str]:
    """Split a body into top-level statements, respecting begin/end nesting."""
    out, depth, cur = [], 0, []
    tokens = re.split(r"(\bbegin\b|\bend\b|;)", block)
    for tok in tokens:
        if tok is None:
            continue
        if tok == "begin":
            depth += 1
            cur.append(tok)
        elif tok == "end":
            depth -= 1
            cur.append(tok)
            if depth == 0:
                out.append("".join(cur))
                cur = []
        elif tok == ";" and depth == 0:
            cur.append(tok)
            out.append("".join(cur))
            cur = []
        else:
            cur.append(tok)
    if "".join(cur).strip():
        out.append("".join(cur))
    return [s for s in out if s.strip()]


def _walk(mod: Module, block: str, guards: set[str]) -> None:
    """Record dependency edges for every assignment in `block` under `guards`.

    Conditions of enclosing `if`/`case` become edges into whatever is assigned
    inside them, which is how control-flow leakage is captured.
    """
    i, n = 0, len(block)
    while i < n:
        m = re.compile(r"\b(if|case|casez|casex)\b\s*\(").search(block, i)
        assign = re.compile(
            r"([A-Za-z_][A-Za-z0-9_$]*)\s*(?:\[[^\]]*\]\s*)?(<=|=)(?!=)([^;]*);"
        ).search(block, i)

        if m and (not assign or m.start() < assign.start()):
            cond, after = _balanced(block, m.end() - 1)
            gs = guards | identifiers(cond)
            if m.group(1) == "if":
                body, after2 = _one_statement(block, after)
                _walk(mod, body, gs)
                rest = block[after2:]
                em = re.match(r"\s*\belse\b", rest)
                if em:
                    ebody, after3 = _one_statement(block, after2 + em.end())
                    _walk(mod, ebody, gs)
                    i = after3
                else:
                    i = after2
            else:  # case
                cbody, after2 = _case_body(block, after)
                # case item labels are themselves compared against the selector
                _walk(mod, cbody, gs)
                i = after2
        elif assign:
            mod.add(assign.group(1), identifiers(assign.group(3)) | guards)
            i = assign.end()
        else:
            break


def _balanced(s: str, open_idx: int) -> tuple[str, int]:
    """Return (contents, index-after-close) for the paren opening at open_idx."""
    depth, j = 0, open_idx
    while j < len(s):
        if s[j] == "(":
            depth += 1
        elif s[j] == ")":
            depth -= 1
            if depth == 0:
                return s[open_idx + 1 : j], j + 1
        j += 1
    return s[open_idx + 1 :], len(s)


def _one_statement(s: str, start: int) -> tuple[str, int]:
    """Return (statement-text, index-after) for exactly one statement.

    A statement is a begin/end block, a nested `if`/`else` (so that `else if`
    chains are consumed whole rather than truncated at the first semicolon, which
    would silently drop the guards of every assignment after the first), a `case`
    through its `endcase`, or a simple assignment through its semicolon.
    """
    m = re.match(r"\s*\bbegin\b", s[start:])
    if m:
        j, depth = start + m.end(), 1
        for tok in re.finditer(r"\b(begin|end)\b", s[j:]):
            depth += 1 if tok.group(1) == "begin" else -1
            if depth == 0:
                return s[j : j + tok.start()], j + tok.end()
        return s[j:], len(s)

    m = re.match(r"\s*\bif\b\s*\(", s[start:])
    if m:
        _, after = _balanced(s, start + m.end() - 1)
        _, after = _one_statement(s, after)
        em = re.match(r"\s*\belse\b", s[after:])
        if em:
            _, after = _one_statement(s, after + em.end())
        return s[start:after], after

    m = re.match(r"\s*\b(case|casez|casex)\b\s*\(", s[start:])
    if m:
        _, after = _balanced(s, start + m.end() - 1)
        _, after = _case_body(s, after)
        return s[start:after], after

    semi = s.find(";", start)
    if semi == -1:
        return s[start:], len(s)
    return s[start : semi + 1], semi + 1


def _case_body(s: str, start: int) -> tuple[str, int]:
    m = re.search(r"\bendcase\b", s[start:])
    if not m:
        return s[start:], len(s)
    return s[start : start + m.start()], start + m.end()


def parse(src: str, module_name: str | None = None) -> Module:
    """Parse one module of a synthesisable Verilog subset into a dependency graph."""
    src = strip_comments(src)
    mods = list(
        re.finditer(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_$]*)(.*?)\bendmodule\b", src, re.DOTALL)
    )
    if not mods:
        raise ValueError("no module found")
    chosen = mods[0]
    if module_name:
        for m in mods:
            if m.group(1) == module_name:
                chosen = m
                break
        else:
            raise ValueError(f"module {module_name!r} not found")

    body = chosen.group(2)
    mod = Module(name=chosen.group(1))
    mod.inputs = _declared(body, "input")
    mod.outputs = _declared(body, "output")

    # continuous assignments
    for m in re.finditer(
        r"\bassign\b\s+([A-Za-z_][A-Za-z0-9_$]*)\s*(?:\[[^\]]*\]\s*)?=([^;]*);", body
    ):
        mod.add(m.group(1), identifiers(m.group(2)))

    # net declarations carrying an initialiser (`wire done_now = running && ...;`)
    # are continuous assignments too; missing them silently empties a cone and
    # turns a leaky design into a false CONSTANT_TIME verdict.
    for m in re.finditer(
        r"\b(?:wire|reg|logic)\b\s*(?:signed\s*)?(?:\[[^\]]*\]\s*)?"
        r"([A-Za-z_][A-Za-z0-9_$]*)\s*=([^;]*);",
        body,
    ):
        mod.add(m.group(1), identifiers(m.group(2)))

    # procedural blocks
    for m in re.finditer(r"\balways\b\s*(@\s*\([^)]*\))?", body):
        stmt, _ = _one_statement(body, m.end())
        _walk(mod, stmt, set())

    return mod


@dataclass
class Verdict:
    module: str
    observation: str
    secrets: list[str]
    reaching: list[str]
    constant_time: bool
    cone_size: int

    def to_dict(self) -> dict:
        return {
            "module": self.module,
            "observation": self.observation,
            "secrets": self.secrets,
            "reaching_secrets": self.reaching,
            "verdict": "CONSTANT_TIME" if self.constant_time else "LEAKY",
            "cone_size": self.cone_size,
        }


def analyse(src: str, observation: str, secrets: list[str],
            module_name: str | None = None) -> Verdict:
    """Decide constant-timeness of `observation` with respect to `secrets`."""
    mod = parse(src, module_name)
    if observation not in mod.deps and observation not in mod.outputs:
        raise ValueError(f"observation {observation!r} is not driven in {mod.name}")
    cone = mod.cone([observation])
    reaching = sorted(cone & set(secrets))
    return Verdict(
        module=mod.name,
        observation=observation,
        secrets=sorted(secrets),
        reaching=reaching,
        constant_time=not reaching,
        cone_size=len(cone),
    )
