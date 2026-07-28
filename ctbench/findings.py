"""A result set, and the one place results turn into an output format.

Before this existed, `_cmd_check` held the only list of verdicts and each new output
format grew its own loop over it. That is fine for one format and a liability by the
third: the SARIF path, the JSON path, and the baseline comparison all need the same
notions of "worst verdict", "which of these are new", and "how does a verdict become
a relative path", and three copies of those drift.

So this module owns the collection, and every emitter is a method on it. A new format
is a new method here, not a new loop somewhere else.

The invariant worth stating: `worst()` treats UNKNOWN as worse than LEAKY. That is
not an aesthetic ordering. A caller who guards only against "leaky" must not be
satisfied by "we could not tell", so the absence of a verdict has to sort above a
negative verdict everywhere the two are compared.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .cone import CONSTANT_TIME, LEAKY, UNKNOWN, Verdict

# Worst-first. Used by `worst()` and by every exit-code decision.
_SEVERITY = {CONSTANT_TIME: 0, LEAKY: 1, UNKNOWN: 2}

EXIT_CLEAN = 0
EXIT_LEAKY = 1
EXIT_UNKNOWN = 2


@dataclass
class Finding:
    """One verdict, plus where it came from."""

    verdict: Verdict
    file: str
    # Set when the verdict was suppressed by a baseline entry: kept in the set so it
    # can still be counted and reported, but excluded from the exit code.
    baselined: bool = False
    baseline_reason: str | None = None

    @property
    def status(self) -> str:
        return self.verdict.status

    def to_dict(self) -> dict:
        d = self.verdict.to_dict()
        d["file"] = self.file
        if self.baselined:
            d["baselined"] = True
            d["baseline_reason"] = self.baseline_reason
        return d

    def key(self) -> tuple:
        """Identity for baseline matching.

        Deliberately excludes `cone_size` and the reason text: a refactor that
        changes how much logic is in the cone, or a reworded message, must not
        silently un-suppress or re-suppress a finding.
        """
        v = self.verdict
        return (self.file, v.module, v.observation, v.status, tuple(v.reaching))


@dataclass
class Findings:
    """An ordered set of findings with the emitters and the exit-code policy."""

    items: list[Finding] = field(default_factory=list)

    def __iter__(self) -> Iterator[Finding]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def add(self, verdict: Verdict, file: str) -> None:
        self.items.append(Finding(verdict=verdict, file=file))

    @classmethod
    def of(cls, pairs: Iterable[tuple[Verdict, str]]) -> Findings:
        f = cls()
        for v, path in pairs:
            f.add(v, path)
        return f

    # -- selection ---------------------------------------------------------

    def by_status(self, status: str) -> list[Finding]:
        return [f for f in self.items if f.status == status]

    @property
    def active(self) -> list[Finding]:
        """Findings that still count — i.e. not suppressed by a baseline."""
        return [f for f in self.items if not f.baselined]

    def worst(self) -> str:
        """The worst *active* status present; CONSTANT_TIME if there are none."""
        if not self.active:
            return CONSTANT_TIME
        return max((f.status for f in self.active), key=lambda s: _SEVERITY[s])

    def exit_code(self) -> int:
        return {CONSTANT_TIME: EXIT_CLEAN, LEAKY: EXIT_LEAKY, UNKNOWN: EXIT_UNKNOWN}[
            self.worst()
        ]

    # -- emitters ----------------------------------------------------------

    def to_list(self) -> list[dict]:
        return [f.to_dict() for f in self.items]

    def to_json(self, indent: int = 2) -> str:
        """One object for a single finding, a list for several.

        The single-file shape predates the multi-file mode and is what the
        documented examples show, so it is preserved rather than regularised.
        """
        payload = self.to_list()
        return json.dumps(payload[0] if len(payload) == 1 else payload, indent=indent)

    def to_sarif(self, version: str = "1.0.0") -> dict:
        from .sarif import to_sarif

        return to_sarif(self.to_list(), version=version)

    def to_table(self) -> str:
        """The human-facing summary: one aligned line per file."""
        mark = {CONSTANT_TIME: "ok     ", LEAKY: "LEAKY  ", UNKNOWN: "UNKNOWN"}
        width = max((len(f.file) for f in self.items), default=1)
        lines = []
        for f in self.items:
            detail = ("no verdict" if f.status == UNKNOWN
                      else ", ".join(f.verdict.reaching) or "—")
            suffix = "  [baselined]" if f.baselined else ""
            lines.append(f"  [{mark[f.status]}] {f.file:<{width}} {detail}{suffix}")
        return "\n".join(lines)

    def summary(self) -> str:
        n = len(self.items)
        parts = [
            f"{len(self.by_status(CONSTANT_TIME))} constant-time",
            f"{len(self.by_status(LEAKY))} leaky",
            f"{len(self.by_status(UNKNOWN))} unknown",
        ]
        base = sum(1 for f in self.items if f.baselined)
        if base:
            parts.append(f"{base} baselined")
        return f"{n} file(s): " + ", ".join(parts)

    def to_dataframe(self):
        """A pandas DataFrame, for notebook users. pandas is not a dependency."""
        try:
            import pandas as pd
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise ImportError(
                "to_dataframe() needs pandas, which ctbench does not depend on. "
                "Install it with `pip install pandas`, or use to_list()."
            ) from exc
        return pd.DataFrame(self.to_list())

    def write(self, path: str | Path, fmt: str = "json") -> None:
        p = Path(path)
        if fmt == "json":
            p.write_text(self.to_json() + "\n")
        elif fmt == "sarif":
            p.write_text(json.dumps(self.to_sarif(), indent=2) + "\n")
        else:
            raise ValueError(f"unknown format {fmt!r}; expected 'json' or 'sarif'")
