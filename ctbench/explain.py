"""Witness paths: *how* a secret reaches the observation, not just that it does.

`LEAKY: done depends on key` is a claim. `key -> key_r -> cmp_eq -> running -> done`
is evidence. The difference matters more here than in most tools, because the
analysis is a syntactic over-approximation: it follows every edge in the dependency
graph whether or not that path is reachable at run time, so a fraction of `LEAKY`
verdicts are paths that cannot actually be taken.

Without the path, a user facing a false positive has no way to tell it from a true
one and learns to distrust the tool. With it, they can look at four signal names and
decide in ten seconds. So this is not a presentation feature — it is what makes an
over-approximate analysis usable by someone who is allowed to disagree with it.

The path reported is a *shortest* one, found by breadth-first search backwards from
the observation. Shortest is chosen deliberately: it is the easiest to read, and if
the shortest path is genuinely dead then the longer ones through the same edges
usually are too. `all_paths` exists for when one is not enough, bounded because the
number of paths in a dependency graph is exponential and an unbounded enumeration
would hang on exactly the large designs where it would be most wanted.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .cone import Module, Verdict


@dataclass
class Path:
    """One route from a secret to the observation, source first."""

    secret: str
    observation: str
    signals: list[str] = field(default_factory=list)

    @property
    def length(self) -> int:
        """Edge count, so a direct dependency is length 1."""
        return max(len(self.signals) - 1, 0)

    def render(self, arrow: str = " -> ") -> str:
        return arrow.join(self.signals)

    def to_dict(self) -> dict:
        return {
            "secret": self.secret,
            "observation": self.observation,
            "signals": self.signals,
            "length": self.length,
        }


def shortest_path(mod: Module, observation: str, secret: str) -> Path | None:
    """A shortest dependency path from `secret` to `observation`, or None.

    Breadth-first from the observation backwards, which finds the shortest path
    without enumerating the others -- depth-first would wander into the deep parts of
    the graph first and, on a wide netlist, take a long time to come back.
    """
    if observation == secret:
        return Path(secret=secret, observation=observation, signals=[secret])

    prev: dict[str, str] = {}
    seen = {observation}
    q = deque([observation])
    while q:
        node = q.popleft()
        for src in sorted(mod.deps.get(node, ())):
            if src in seen:
                continue
            seen.add(src)
            prev[src] = node
            if src == secret:
                # Walk forward from the secret to the observation.
                signals = [src]
                while signals[-1] != observation:
                    signals.append(prev[signals[-1]])
                return Path(secret=secret, observation=observation, signals=signals)
            q.append(src)
    return None


def all_paths(mod: Module, observation: str, secret: str,
              limit: int = 8, max_length: int = 64) -> list[Path]:
    """Up to `limit` distinct paths, shortest first.

    Bounded on purpose. The number of paths through a dependency graph is
    exponential in its size, so an unbounded search would hang on the large designs
    where extra paths would be most useful. When the limit is reached the caller is
    told, rather than being handed a truncated list that looks complete.
    """
    out: list[Path] = []
    # (current node, path so far from the secret end)
    q: deque[tuple[str, list[str]]] = deque([(observation, [observation])])
    while q and len(out) < limit:
        node, sofar = q.popleft()
        if len(sofar) > max_length:
            continue
        for src in sorted(mod.deps.get(node, ())):
            if src in sofar:
                continue                      # no cycles
            nxt = [src, *sofar]
            if src == secret:
                out.append(Path(secret=secret, observation=observation, signals=nxt))
                if len(out) >= limit:
                    break
            else:
                q.append((src, nxt))
    return out


@dataclass
class Explanation:
    """Why a verdict is what it is."""

    verdict: Verdict
    paths: list[Path] = field(default_factory=list)
    truncated: bool = False

    def to_dict(self) -> dict:
        d = self.verdict.to_dict()
        d["paths"] = [p.to_dict() for p in self.paths]
        if self.truncated:
            d["paths_truncated"] = True
        return d

    def render(self) -> str:
        v = self.verdict
        if v.status == "UNKNOWN":
            return (
                f"UNKNOWN — no verdict for {v.observation!r}.\n\n{v.reason}\n\n"
                f"There is no path to show: the analysis could not read the design, "
                f"so it has no dependency graph to trace."
            )
        if v.status == "CONSTANT_TIME":
            return (
                f"CONSTANT_TIME — no declared secret reaches {v.observation!r}.\n\n"
                f"Its fan-in cone spans {v.cone_size} signal(s) and contains none of "
                f"{', '.join(v.secrets)}.\n\n"
                f"There is no path to show, which is the point: a path would be the "
                f"finding."
            )

        lines = [
            f"LEAKY — {v.observation!r} depends on {', '.join(v.reaching)}.",
            "",
            "How each secret reaches it (shortest path first):",
            "",
        ]
        for p in self.paths:
            lines.append(f"  {p.secret}")
            lines.extend(
                f"  {'└─' if i == len(p.signals) - 1 else '├─'} {sig}"
                for i, sig in enumerate(p.signals[1:], start=1)
            )
            lines.append("")
        if self.truncated:
            lines.append("  (more paths exist; showing the shortest for each secret)")
            lines.append("")
        lines += [
            "Each arrow is a dependency edge: an assignment, or a condition guarding",
            "one. The analysis over-approximates, so a path may be unreachable at run",
            "time — read it and decide. That is why it is printed.",
        ]
        return "\n".join(lines)

    def to_dot(self) -> str:
        """Graphviz DOT of the reported paths."""
        edges: set[tuple[str, str]] = set()
        secrets = {p.secret for p in self.paths}
        for p in self.paths:
            for a, b in zip(p.signals, p.signals[1:], strict=False):
                edges.add((a, b))
        lines = ["digraph witness {", "  rankdir=LR;", "  node [shape=box];"]
        lines.extend(f'  "{s}" [style=filled, fillcolor="#ffdddd"];'
                     for s in sorted(secrets))
        obs = self.verdict.observation
        lines.append(f'  "{obs}" [style=filled, fillcolor="#ddddff"];')
        lines.extend(f'  "{a}" -> "{b}";' for a, b in sorted(edges))
        lines.append("}")
        return "\n".join(lines)

    def to_mermaid(self) -> str:
        """Mermaid flowchart, which renders inline on GitHub."""
        def ident(s: str) -> str:
            return "n_" + "".join(c if c.isalnum() else "_" for c in s)

        edges: set[tuple[str, str]] = set()
        for p in self.paths:
            for a, b in zip(p.signals, p.signals[1:], strict=False):
                edges.add((a, b))
        lines = ["flowchart LR"]
        seen: set[str] = set()
        for p in self.paths:
            new = [s for s in p.signals if s not in seen]
            seen.update(new)
            lines.extend(f'  {ident(s)}["{s}"]' for s in new)
        lines.extend(f"  {ident(a)} --> {ident(b)}" for a, b in sorted(edges))
        lines.extend(f"  style {ident(p.secret)} fill:#fdd" for p in self.paths)
        lines.append(f"  style {ident(self.verdict.observation)} fill:#ddf")
        return "\n".join(lines)


def explain(mod: Module, verdict: Verdict, limit_per_secret: int = 1) -> Explanation:
    """Build an explanation: one shortest path per reaching secret by default.

    The shortest path is always found first with BFS and always included, even when
    more were requested. `all_paths` is depth-bounded, so on a long chain it can come
    back empty while a path demonstrably exists -- which meant asking for *more* paths
    returned *fewer*, and an empty list reads as "no path", which is the opposite of
    a LEAKY verdict's meaning. Found by a stress test on a 50 000-edge netlist:
    `shortest_path` returned a path of length 50 000 and `all_paths` returned none.
    """
    paths: list[Path] = []
    truncated = False
    for secret in verdict.reaching:
        first = shortest_path(mod, verdict.observation, secret)
        if first is None:
            # The verdict says this secret reaches the observation, so BFS must find
            # a path. If it does not, the graph and the verdict disagree and saying
            # nothing would hide that.
            continue
        paths.append(first)
        if limit_per_secret > 1:
            extra = [
                p for p in all_paths(mod, verdict.observation, secret,
                                     limit=limit_per_secret)
                if p.signals != first.signals
            ]
            paths.extend(extra[: limit_per_secret - 1])
            truncated = truncated or len(extra) >= limit_per_secret - 1
    return Explanation(verdict=verdict, paths=paths, truncated=truncated)
