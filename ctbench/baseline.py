"""Accepting known findings, so an existing codebase can adopt the check.

The standard failure mode for a new checker on an old codebase: day one shows 200
findings, nobody triages 200 findings, the job gets marked `continue-on-error`, and
the tool is now decoration. A baseline fixes that by recording what was already there
and failing only on what is new.

Two properties matter more than the feature itself.

**A baseline must not be able to hide a leak it never saw.** Entries are matched on
the identity of a finding -- file, module, observation, status, and the exact set of
reaching secrets -- so a *different* leak in an already-baselined file is still
reported. Suppressing by filename would be much simpler and would quietly hide the
next bug in every file anybody ever baselined.

**A baselined UNKNOWN stays UNKNOWN.** It is excluded from the exit code, because the
user has said "I know, I will deal with it" -- but the verdict itself is never
rewritten to CONSTANT_TIME, it is still counted, and it is still printed. The
abstention has to survive being acknowledged, otherwise the baseline becomes a way to
launder "we could not tell" into "it is fine".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .cone import UNKNOWN
from .findings import Findings

SCHEMA = "ctbench-baseline/1"


class BaselineError(ValueError):
    """The baseline file cannot be read, so it is not applied."""


@dataclass
class BaselineEntry:
    file: str
    module: str
    observation: str
    status: str
    reaching: tuple[str, ...]
    reason: str = ""

    def key(self) -> tuple:
        return (self.file, self.module, self.observation, self.status, tuple(self.reaching))

    def to_dict(self) -> dict:
        d = {
            "file": self.file,
            "module": self.module,
            "observation": self.observation,
            "verdict": self.status,
            "reaching_secrets": list(self.reaching),
        }
        if self.reason:
            d["reason"] = self.reason
        return d


class Baseline:
    """A set of accepted findings."""

    def __init__(self, entries: list[BaselineEntry] | None = None) -> None:
        self.entries = entries or []
        self._index = {e.key(): e for e in self.entries}

    # -- io ----------------------------------------------------------------

    @classmethod
    def from_findings(cls, findings: Findings, reason: str = "") -> Baseline:
        return cls([
            BaselineEntry(
                file=f.file,
                module=f.verdict.module,
                observation=f.verdict.observation,
                status=f.status,
                reaching=tuple(f.verdict.reaching),
                reason=reason,
            )
            for f in findings
            # A clean file has nothing to accept.
            if f.status != "CONSTANT_TIME"
        ])

    @classmethod
    def load(cls, path: str | Path) -> Baseline:
        p = Path(path)
        try:
            raw = json.loads(p.read_text())
        except FileNotFoundError as exc:
            raise BaselineError(
                f"baseline {str(p)!r} does not exist. Create it with "
                f"`ctbench check ... --update-baseline {p}`."
            ) from exc
        except json.JSONDecodeError as exc:
            # Refuse rather than proceed with no suppressions: silently ignoring a
            # corrupt baseline turns a green run into a misleading one.
            raise BaselineError(
                f"baseline {str(p)!r} is not valid JSON: {exc}. Refusing to run with a "
                f"baseline that cannot be read -- delete it and regenerate, or fix it."
            ) from exc
        if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
            raise BaselineError(
                f"baseline {str(p)!r} is not a ctbench baseline "
                f"(expected schema {SCHEMA!r}). Regenerate it with --update-baseline."
            )
        entries = []
        for i, e in enumerate(raw.get("accepted", [])):
            try:
                entries.append(BaselineEntry(
                    file=e["file"], module=e["module"], observation=e["observation"],
                    status=e["verdict"], reaching=tuple(e.get("reaching_secrets", [])),
                    reason=e.get("reason", ""),
                ))
            except (KeyError, TypeError) as exc:
                raise BaselineError(
                    f"baseline {str(p)!r} entry {i} is malformed: missing {exc}."
                ) from exc
        return cls(entries)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps({
            "schema": SCHEMA,
            "note": (
                "Findings accepted as known. ctbench fails only on findings NOT in "
                "this list. An entry matches only the exact finding recorded here: a "
                "different leak in the same file is still reported. Regenerate with "
                "`ctbench check ... --update-baseline`."
            ),
            "accepted": [e.to_dict() for e in self.entries],
        }, indent=2) + "\n")

    # -- application -------------------------------------------------------

    def apply(self, findings: Findings) -> Findings:
        """Mark findings present in the baseline, in place, and return them."""
        for f in findings:
            entry = self._index.get(f.key())
            if entry is not None:
                f.baselined = True
                f.baseline_reason = entry.reason or "accepted in baseline"
                if f.status == UNKNOWN:
                    # Acknowledged, never converted. It still reads as UNKNOWN
                    # everywhere it is printed or exported.
                    f.baseline_reason += " (still UNKNOWN: no verdict was reached)"
        return findings

    def stale(self, findings: Findings) -> list[BaselineEntry]:
        """Entries that matched nothing -- the finding was fixed, or moved."""
        seen = {f.key() for f in findings}
        return [e for e in self.entries if e.key() not in seen]

    def __len__(self) -> int:
        return len(self.entries)
