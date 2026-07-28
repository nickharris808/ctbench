"""ctbench — matched-pair constant-time RTL benchmark corpus."""

from .cone import Module, Verdict, analyse, parse
from .score import Score, format_report, load_manifest, score

__version__ = "1.0.0"
__all__ = [
           "Module",
           "Score",
           "Verdict",
           "__version__",
           "analyse",
           "format_report",
           "load_manifest",
           "parse",
           "score",
]
