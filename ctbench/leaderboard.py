"""Submissions and the leaderboard.

A corpus becomes a benchmark only when other people can submit to it and be ranked
by a rule they did not choose. This module is that rule.

**The ranking is lexicographic, and soundness comes first.**

    (sound, pairs_separated, correct, -imprecise, -abstained)

A tool that reports one leaky design as safe ranks below every sound tool, no matter
how accurate it is otherwise — because that error ships a vulnerability and the
others cost engineering time. Within the sound tools, separating matched pairs
counts for more than raw accuracy, since a pair is the only evidence that a tool is
discriminating rather than guessing a constant.

Abstention is permitted and tracked. A tool that answers `UNKNOWN` is ranked below
one that answers correctly, and above one that answers wrongly. Honest uncertainty
should not be punished as hard as confident error.

**Submissions are validated before they are scored.** A submission that omits
fixtures, invents fixture names, or uses verdicts outside the vocabulary is rejected
with a reason rather than partially credited — otherwise the cheapest way up the
board is to answer only the easy half.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .score import VERDICTS, Score, load_manifest, score

SUBMISSION_VERSION = 1
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._+-]{0,63}$")


class InvalidSubmission(Exception):
    """A submission cannot be scored as-is."""


@dataclass
class Submission:
    tool: str
    version: str
    verdicts: dict[str, str]
    url: str = ""
    notes: str = ""
    submitted: str = ""
    #: how the tool decides; free text, shown on the board so results are interpretable
    method: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "submission_version": SUBMISSION_VERSION,
            "tool": self.tool,
            "version": self.version,
            "url": self.url,
            "method": self.method,
            "notes": self.notes,
            "submitted": self.submitted,
            "verdicts": self.verdicts,
        }


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise InvalidSubmission(message)


def parse_submission(data: dict[str, Any], manifest: dict | None = None) -> Submission:
    """Validate a submission payload, or raise `InvalidSubmission` explaining why."""
    _require(isinstance(data, dict), "submission must be a JSON object")

    ver = data.get("submission_version", SUBMISSION_VERSION)
    _require(
        ver == SUBMISSION_VERSION,
        f"submission_version {ver!r} is not supported (expected {SUBMISSION_VERSION})",
    )
    for key in ("tool", "version", "verdicts"):
        _require(key in data, f"missing required field {key!r}")

    tool = str(data["tool"]).strip()
    _require(bool(_NAME_RE.match(tool)), f"tool name {tool!r} is not a plain identifier")

    verdicts = data["verdicts"]
    _require(isinstance(verdicts, dict), "'verdicts' must be an object of file -> verdict")

    man = manifest or load_manifest()
    expected = {e["file"] for e in man["scored"]}
    unscored = {e["file"] for e in man["unscored"]}
    got = set(verdicts)

    unknown = got - expected - unscored
    _require(not unknown, f"verdicts name fixtures not in the benchmark: {sorted(unknown)}")

    missing = expected - got
    _require(
        not missing,
        "a submission must cover every scored fixture; missing: "
        f"{sorted(missing)}. Use \"UNKNOWN\" to abstain rather than omitting an entry.",
    )

    bad = {f: v for f, v in verdicts.items() if str(v).upper() not in VERDICTS}
    _require(not bad, f"verdicts outside the vocabulary {VERDICTS}: {bad}")

    return Submission(
        tool=tool,
        version=str(data["version"]).strip(),
        verdicts={f: str(v).upper() for f, v in verdicts.items() if f in expected},
        url=str(data.get("url", "")).strip(),
        notes=str(data.get("notes", "")).strip(),
        method=str(data.get("method", "")).strip(),
        submitted=str(data.get("submitted", "")).strip(),
    )


def rank_key(s: Score) -> tuple:
    """The ranking rule. Soundness dominates; pair separation outranks raw accuracy."""
    return (
        1 if s.sound else 0,
        s.pairs_separated,
        s.correct,
        -len(s.imprecise),
        -len(s.abstained),
    )


@dataclass
class Entry:
    submission: Submission
    score: Score = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.submission.tool,
            "version": self.submission.version,
            "url": self.submission.url,
            "method": self.submission.method,
            "submitted": self.submission.submitted,
            "sound": self.score.sound,
            "pairs_separated": self.score.pairs_separated,
            "pairs_total": self.score.pairs_total,
            "correct": self.score.correct,
            "total": self.score.total,
            "accuracy": round(self.score.accuracy, 4),
            "imprecise": len(self.score.imprecise),
            "abstained": len(self.score.abstained),
            "unsound_verdicts": self.score.unsound,
            "out_of_remit_control_passed": self.score.out_of_remit_ok,
        }


def build_leaderboard(
    submissions: list[dict[str, Any]], manifest: dict | None = None
) -> list[Entry]:
    """Validate, score, and rank a set of submissions."""
    man = manifest or load_manifest()
    entries = [
        Entry(sub, score(sub.verdicts, man))
        for sub in (parse_submission(d, man) for d in submissions)
    ]
    entries.sort(key=lambda e: rank_key(e.score), reverse=True)
    return entries


def load_registry(path: Path | str) -> list[dict[str, Any]]:
    """Read a directory of submission files, or a single JSON array."""
    p = Path(path)
    if p.is_dir():
        return [json.loads(f.read_text()) for f in sorted(p.glob("*.json"))]
    data = json.loads(p.read_text())
    return data if isinstance(data, list) else [data]


def format_leaderboard(entries: list[Entry]) -> str:
    """A Markdown table, ready to paste into a README."""
    lines = [
        "| # | Tool | Sound | Pairs | Correct | Imprecise | Abstained | Control |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, e in enumerate(entries, 1):
        s, sub = e.score, e.submission
        name = f"[{sub.tool} {sub.version}]({sub.url})" if sub.url else f"{sub.tool} {sub.version}"
        control = (
            "—" if s.out_of_remit_ok is None else ("pass" if s.out_of_remit_ok else "**wolf**")
        )
        lines.append(
            f"| {i} | {name} | {'yes' if s.sound else '**NO**'} | "
            f"{s.pairs_separated}/{s.pairs_total} | {s.correct}/{s.total} | "
            f"{len(s.imprecise)} | {len(s.abstained)} | {control} |"
        )
    lines += [
        "",
        (
            "Ranked by soundness first, then matched pairs separated, then correct "
            "verdicts, then fewer imprecise and fewer abstained. An unsound tool — one "
            "that called a leaky design safe — ranks below every sound tool regardless "
            "of accuracy."
        ),
    ]
    return "\n".join(lines)


def make_submission(
    verdicts: dict[str, str],
    tool: str,
    version: str,
    *,
    url: str = "",
    method: str = "",
    notes: str = "",
    when: datetime | None = None,
) -> dict[str, Any]:
    """Build a submission payload from a set of verdicts."""
    stamp = (when or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    return Submission(
        tool=tool, version=version, verdicts=verdicts, url=url,
        method=method, notes=notes, submitted=stamp,
    ).to_dict()
