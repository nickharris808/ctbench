"""ctbench — matched-pair constant-time RTL benchmark corpus and reference checker.

Two entry points that differ only in how they report a refusal:

    from ctbench import check, analyse

`analyse` raises an `AnalysisRefused` subclass when it cannot read the design;
`check` returns a Verdict whose `status` is `UNKNOWN` and whose `reason` says why.
Use `analyse` when a refusal should stop the program, `check` when you must report on
every input and one unreadable file should not abort the run.

`Verdict.constant_time` is False for UNKNOWN, so code written as
`if v.constant_time: ship()` stays correct without knowing the third state exists.
"""

from .cone import (
    CONSTANT_TIME,
    LEAKY,
    UNKNOWN,
    AnalysisRefused,
    Module,
    ModuleNotFound,
    NoModuleFound,
    UndrivenObservation,
    UnknownObservation,
    UnsupportedConstruct,
    Verdict,
    analyse,
    check,
    parse,
    unsupported_constructs,
)
from .findings import Finding, Findings
from .netlist import NetlistError, load_netlist, parse_netlist
from .score import Score, format_report, load_manifest, score

__version__ = "1.1.0"
__all__ = [
    "CONSTANT_TIME",
    "LEAKY",
    "UNKNOWN",
    "AnalysisRefused",
    "Finding",
    "Findings",
    "Module",
    "ModuleNotFound",
    "NetlistError",
    "NoModuleFound",
    "Score",
    "UndrivenObservation",
    "UnknownObservation",
    "UnsupportedConstruct",
    "Verdict",
    "__version__",
    "analyse",
    "check",
    "format_report",
    "load_manifest",
    "load_netlist",
    "parse",
    "parse_netlist",
    "score",
    "unsupported_constructs",
]
