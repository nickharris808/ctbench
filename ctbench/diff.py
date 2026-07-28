"""What changed between two runs.

A repo-wide report gets skimmed and ignored; a finding attributable to *this* change
gets fixed. That is the entire argument for this module, and it is why the primary
consumer is the pull-request comment rather than a human at a terminal.

The classification is deliberately four-way rather than two. "Introduced" and "fixed"
are obvious. The other two are the ones that catch real problems:

* **changed** -- same file and observation, different reaching secrets. Neither
  introduced nor fixed; a leak that moved. Collapsing it into either would lose it.
* **regressed to UNKNOWN** -- a file that used to get a verdict no longer does,
  usually because someone added a construct the analysis cannot read. Nothing is
  newly leaky, so a naive diff calls it an improvement. It is the opposite: coverage
  was lost, and the honest report says so.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .cone import CONSTANT_TIME, LEAKY, UNKNOWN
from .findings import Finding, Findings


def _index(f: Findings) -> dict[tuple[str, str], Finding]:
    """Findings keyed by (file, observation) -- the identity of a *check*.

    Not keyed by verdict: the point is to compare the same check across two runs, so
    the key has to be stable when the answer changes.
    """
    return {(x.file, x.verdict.observation): x for x in f}


@dataclass
class Diff:
    introduced: list[Finding] = field(default_factory=list)
    fixed: list[Finding] = field(default_factory=list)
    changed: list[tuple[Finding, Finding]] = field(default_factory=list)
    lost_coverage: list[tuple[Finding, Finding]] = field(default_factory=list)
    gained_coverage: list[tuple[Finding, Finding]] = field(default_factory=list)
    unchanged: int = 0
    added_files: list[Finding] = field(default_factory=list)
    removed_files: list[Finding] = field(default_factory=list)

    @property
    def is_regression(self) -> bool:
        """Anything that should fail a pull request.

        Losing coverage counts. A file that stopped being analysable is not an
        improvement just because it stopped reporting a leak.
        """
        return bool(self.introduced or self.changed or self.lost_coverage)

    def exit_code(self) -> int:
        return 1 if self.is_regression else 0

    def to_dict(self) -> dict:
        return {
            "introduced": [f.to_dict() for f in self.introduced],
            "fixed": [f.to_dict() for f in self.fixed],
            "changed": [{"before": a.to_dict(), "after": b.to_dict()}
                        for a, b in self.changed],
            "lost_coverage": [{"before": a.to_dict(), "after": b.to_dict()}
                              for a, b in self.lost_coverage],
            "gained_coverage": [{"before": a.to_dict(), "after": b.to_dict()}
                                for a, b in self.gained_coverage],
            "added_files": [f.to_dict() for f in self.added_files],
            "removed_files": [f.to_dict() for f in self.removed_files],
            "unchanged": self.unchanged,
            "regression": self.is_regression,
        }

    def render(self) -> str:
        if not any([self.introduced, self.fixed, self.changed, self.lost_coverage,
                    self.gained_coverage, self.added_files, self.removed_files]):
            return f"No change. {self.unchanged} check(s) identical."

        out: list[str] = []
        if self.introduced:
            out.append(f"INTRODUCED ({len(self.introduced)}):")
            out += [f"  + {f.file}: {f.verdict.observation} now depends on "
                    f"{', '.join(f.verdict.reaching)}" for f in self.introduced]
            out.append("")
        if self.lost_coverage:
            out.append(f"COVERAGE LOST ({len(self.lost_coverage)}):")
            out += [f"  ? {a.file}: was {a.status}, now UNKNOWN — this file is no "
                    f"longer being checked" for a, _ in self.lost_coverage]
            out.append("")
        if self.changed:
            out.append(f"CHANGED ({len(self.changed)}):")
            out += [f"  ~ {a.file}: {', '.join(a.verdict.reaching) or 'none'} -> "
                    f"{', '.join(b.verdict.reaching) or 'none'}" for a, b in self.changed]
            out.append("")
        if self.fixed:
            out.append(f"FIXED ({len(self.fixed)}):")
            out += [f"  - {f.file}: {f.verdict.observation} no longer leaks"
                    for f in self.fixed]
            out.append("")
        if self.gained_coverage:
            out.append(f"COVERAGE GAINED ({len(self.gained_coverage)}):")
            out += [f"  ✓ {b.file}: was UNKNOWN, now {b.status}"
                    for _, b in self.gained_coverage]
            out.append("")
        if self.added_files:
            out.append(f"NEW FILES ({len(self.added_files)}): "
                       + ", ".join(f.file for f in self.added_files))
        if self.removed_files:
            out.append(f"REMOVED FILES ({len(self.removed_files)}): "
                       + ", ".join(f.file for f in self.removed_files))
        out.append(f"\n{self.unchanged} check(s) unchanged.")
        return "\n".join(out)

    def to_markdown(self) -> str:
        """A pull-request comment."""
        head = ("### ❌ Constant-time regression" if self.is_regression
                else "### ✅ No constant-time regression")
        rows = ["", "| Change | File | Detail |", "|---|---|---|"]
        rows.extend(
            f"| **introduced** | `{f.file}` | `{f.verdict.observation}` depends on "
            f"{', '.join(f'`{s}`' for s in f.verdict.reaching)} |"
            for f in self.introduced
        )
        for a, _ in self.lost_coverage:
            rows.append(f"| **coverage lost** | `{a.file}` | was {a.status}, "
                        f"now UNKNOWN — no longer checked |")
        rows.extend(
            f"| changed | `{a.file}` | {', '.join(a.verdict.reaching) or '—'} → "
            f"{', '.join(b.verdict.reaching) or '—'} |"
            for a, b in self.changed
        )
        rows.extend(f"| fixed | `{f.file}` | no longer leaks |" for f in self.fixed)
        rows.extend(f"| coverage gained | `{b.file}` | now {b.status} |"
                    for _, b in self.gained_coverage)
        if len(rows) == 3:
            rows.append("| — | — | nothing changed |")
        return head + "\n" + "\n".join(rows) + (
            f"\n\n<sub>{self.unchanged} check(s) unchanged. "
            f"Coverage loss counts as a regression: a file that stopped being "
            f"analysable is not an improvement.</sub>"
        )


def diff(before: Findings, after: Findings) -> Diff:
    """Classify what changed between two runs."""
    b, a = _index(before), _index(after)
    d = Diff()

    for key, new in a.items():
        old = b.get(key)
        if old is None:
            d.added_files.append(new)
            continue
        if old.status == new.status and old.verdict.reaching == new.verdict.reaching:
            d.unchanged += 1
        elif new.status == UNKNOWN and old.status != UNKNOWN:
            d.lost_coverage.append((old, new))
        elif old.status == UNKNOWN and new.status != UNKNOWN:
            d.gained_coverage.append((old, new))
        elif old.status == CONSTANT_TIME and new.status == LEAKY:
            d.introduced.append(new)
        elif old.status == LEAKY and new.status == CONSTANT_TIME:
            d.fixed.append(new)
        else:
            d.changed.append((old, new))

    for key, old in b.items():
        if key not in a:
            d.removed_files.append(old)
    return d


def load_findings(path: str | Path) -> Findings:
    """Read a `ctbench check --json` result file back into a Findings."""
    from .cone import Verdict

    raw = json.loads(Path(path).read_text())
    if isinstance(raw, dict):
        raw = [raw]
    f = Findings()
    for d in raw:
        f.add(
            Verdict(
                module=d.get("module", "?"),
                observation=d.get("observation", "done"),
                secrets=d.get("secrets", []),
                reaching=d.get("reaching_secrets", []),
                cone_size=d.get("cone_size", 0),
                status=d.get("verdict", UNKNOWN),
                reason=d.get("reason"),
            ),
            d.get("file", "?"),
        )
    return f
