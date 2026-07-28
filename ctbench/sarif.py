"""SARIF 2.1.0 output, so verdicts land in GitHub code scanning.

A verdict that lives in CI log output gets read once, by whoever opened the run.
The same verdict as SARIF becomes an annotation on the pull request, an entry in
the repository's security tab, and a thing that can block a merge. That is the
difference between a tool someone tried and a tool someone adopted, and it costs
one output format.

Two decisions here are deliberate and worth stating.

**UNKNOWN is reported, not omitted.** The obvious reading of SARIF is "results are
findings", so a file with no leak produces nothing. But a file the analysis could
not read is exactly the case a reviewer must see: silence would be indistinguishable
from a clean pass, which is the confusion this whole tool exists to prevent. It is
emitted at `warning` level with the construct that stopped the analysis.

**Clean files produce no result, but do appear in `invocation`.** SARIF has no
natural "this was checked and was fine" result, and inventing one at `note` level
clutters the diff. Instead every checked file is listed in the run's `artifacts`,
so a consumer can tell "checked, clean" from "never looked at".
"""

from __future__ import annotations

from typing import Any

SARIF_VERSION = "2.1.0"
SCHEMA = "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json"

RULES = [
    {
        "id": "CT001",
        "name": "SecretDependentCompletionTiming",
        "shortDescription": {"text": "Completion signal depends on a secret input"},
        "fullDescription": {
            "text": (
                "The observation signal's fan-in cone contains a declared secret, so "
                "the cycle on which it asserts is a function of secret data and "
                "completion timing reveals secret-dependent behaviour."
            )
        },
        "help": {
            "text": (
                "Make the completion condition a function of a data-oblivious counter "
                "rather than of operand values: run a fixed number of cycles and drop "
                "the early-exit branch."
            )
        },
        "defaultConfiguration": {"level": "error"},
        "properties": {"tags": ["security", "side-channel", "timing", "hardware"]},
    },
    {
        "id": "CT002",
        "name": "AnalysisReachedNoVerdict",
        "shortDescription": {"text": "Design could not be analysed; no verdict was reached"},
        "fullDescription": {
            "text": (
                "The file uses a construct outside the supported Verilog subset, so "
                "dependency edges would be invisible to the cone analysis. No verdict "
                "is returned. This file has NOT been shown to be constant-time."
            )
        },
        "help": {
            "text": (
                "The analysis reads one flat module of assign statements, net "
                "declarations with initialisers, and always blocks. Flatten the module, "
                "or analyse the submodule that drives the completion signal directly."
            )
        },
        "defaultConfiguration": {"level": "warning"},
        "properties": {"tags": ["security", "coverage", "hardware"]},
    },
]


def _result(rule_id: str, level: str, text: str, file: str, line: int = 1) -> dict[str, Any]:
    return {
        "ruleId": rule_id,
        "ruleIndex": next(i for i, r in enumerate(RULES) if r["id"] == rule_id),
        "level": level,
        "message": {"text": text},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": file},
                    "region": {"startLine": line},
                }
            }
        ],
    }


def to_sarif(results: list[dict], version: str = "1.0.0") -> dict[str, Any]:
    """Render verdict dicts (as produced by `Verdict.to_dict`) as a SARIF log."""
    out: list[dict] = []
    for d in results:
        f = d.get("file", "<stdin>")
        if d["verdict"] == "LEAKY":
            reaching = ", ".join(d["reaching_secrets"])
            out.append(_result(
                "CT001", "error",
                f"Completion signal '{d['observation']}' depends on secret input(s): "
                f"{reaching}. Timing reveals secret-dependent behaviour.",
                f,
            ))
        elif d["verdict"] == "UNKNOWN":
            out.append(_result(
                "CT002", "warning",
                f"No verdict for '{d['observation']}': {d.get('reason', 'analysis refused')} "
                f"This file has NOT been shown to be constant-time.",
                f,
                # the refusal locates the offending construct; use it when present
                _line_from_reason(d.get("reason", "")),
            ))
    return {
        "$schema": SCHEMA,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "ctbench",
                        "version": version,
                        "informationUri": "https://github.com/nickharris808/ctbench",
                        "rules": RULES,
                    }
                },
                # Every file that was looked at, so "checked and clean" is
                # distinguishable from "never analysed".
                "artifacts": [
                    {"location": {"uri": d.get("file", "<stdin>")},
                     "description": {"text": f"verdict: {d['verdict']}"}}
                    for d in results
                ],
                "results": out,
            }
        ],
    }


def _line_from_reason(reason: str) -> int:
    """Pull the line number out of an UnsupportedConstruct message, else line 1."""
    import re

    m = re.match(r"line (\d+):", reason or "")
    return int(m.group(1)) if m else 1
