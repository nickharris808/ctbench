"""Scoring for ctbench.

A tool submits a JSON mapping of fixture file name to `"CONSTANT_TIME"`,
`"LEAKY"`, or `"UNKNOWN"`, and is graded against the manifest's expected verdicts.

The scoring is deliberately asymmetric, because the two error directions are not
equally bad:

* A **false CONSTANT_TIME** (unsound) says a leaky design is safe.  This is the
  error that ships a vulnerability, and it is reported separately and first.
* A **false LEAKY** (imprecise) says a safe design leaks.  This wastes engineering
  time but breaks nothing.
* **UNKNOWN** is neither.  A tool that abstains is scored as abstaining rather than
  being silently counted as correct; refusing to answer is honest, and honesty is
  not penalised as heavily as being wrong.

The `out_of_remit` fixture is scored but called out separately: it is genuinely
constant-time while being functionally incorrect, so a tool that reports LEAKY on
it has confused two different properties.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

VERDICTS = ("CONSTANT_TIME", "LEAKY", "UNKNOWN")
MANIFEST = Path(__file__).resolve().parent / "fixtures" / "manifest.json"


def load_manifest(path: Path | str | None = None) -> dict:
    return json.loads(Path(path or MANIFEST).read_text())


@dataclass
class Score:
    total: int = 0
    correct: int = 0
    unsound: list[str] = field(default_factory=list)      # said safe, is leaky
    imprecise: list[str] = field(default_factory=list)    # said leaky, is safe
    abstained: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    out_of_remit_ok: bool | None = None
    pairs_separated: int = 0
    pairs_total: int = 0

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def sound(self) -> bool:
        """No leaky fixture was reported safe."""
        return not self.unsound

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "correct": self.correct,
            "accuracy": round(self.accuracy, 4),
            "sound": self.sound,
            "unsound_verdicts": self.unsound,
            "imprecise_verdicts": self.imprecise,
            "abstained": self.abstained,
            "missing": self.missing,
            "out_of_remit_control_passed": self.out_of_remit_ok,
            "pairs_separated": self.pairs_separated,
            "pairs_total": self.pairs_total,
        }


def score(submission: dict[str, str], manifest: dict | None = None) -> Score:
    """Grade `submission` (fixture file -> verdict) against the manifest."""
    man = manifest or load_manifest()
    s = Score()
    by_pair: dict[str, dict[str, str]] = {}

    for entry in man["scored"]:
        f, expected, role = entry["file"], entry["expected"], entry.get("role", "")
        s.total += 1
        got = submission.get(f)
        if got is None:
            s.missing.append(f)
            continue
        got = got.upper()
        if got not in VERDICTS:
            raise ValueError(f"{f}: verdict {got!r} not one of {VERDICTS}")

        if got == "UNKNOWN":
            s.abstained.append(f)
        elif got == expected:
            s.correct += 1
        elif expected == "LEAKY":
            s.unsound.append(f)
        else:
            s.imprecise.append(f)

        if role == "out_of_remit":
            s.out_of_remit_ok = got == expected
        if entry.get("pair") and role in ("positive", "negative"):
            by_pair.setdefault(entry["pair"], {})[role] = got

    for roles in by_pair.values():
        if "positive" in roles and "negative" in roles:
            s.pairs_total += 1
            if roles["positive"] == "CONSTANT_TIME" and roles["negative"] == "LEAKY":
                s.pairs_separated += 1
    return s


def format_report(s: Score) -> str:
    """Human-readable scorecard."""
    lines = [
        "ctbench scorecard",
        "=" * 52,
        f"  fixtures scored     {s.correct}/{s.total}  ({s.accuracy:.1%})",
        f"  pairs separated     {s.pairs_separated}/{s.pairs_total}",
        f"  sound               {'YES' if s.sound else 'NO'}",
    ]
    if s.out_of_remit_ok is not None:
        lines.append(
            f"  out-of-remit ctrl   {'PASS' if s.out_of_remit_ok else 'FAIL (cried wolf)'}"
        )
    if s.unsound:
        lines += ["", "  UNSOUND — reported safe, is leaky:"]
        lines += [f"    - {f}" for f in s.unsound]
    if s.imprecise:
        lines += ["", "  imprecise — reported leaky, is safe:"]
        lines += [f"    - {f}" for f in s.imprecise]
    if s.abstained:
        lines += ["", f"  abstained on {len(s.abstained)}: " + ", ".join(s.abstained)]
    if s.missing:
        lines += ["", f"  missing {len(s.missing)}: " + ", ".join(s.missing)]
    return "\n".join(lines)
