"""Export the corpus as a Hugging Face dataset.

Loading scripts are deprecated on the Hub, so this emits plain JSONL plus a dataset
card with YAML front-matter — the shape the Hub loads natively with
`load_dataset("nickh007/hw-verify")` and no trust_remote_code.

Two design choices worth stating:

* the **full Verilog source** is inlined in each record. A dataset of file names
  would be useless to anyone evaluating a model, and the fixtures are small.
* the **licence is per-record**. Four fixtures derive from picorv32 and stay under
  the upstream ISC licence; the rest are CC-BY-4.0. Flattening that into a single
  dataset-level licence would misstate it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .score import load_manifest

ISC_FIXTURES = frozenset({
    "pcpi_div.v", "pcpi_mul.v", "pcpi_div_wiped.v", "pcpi_div_halfwipe.v",
})

CARD = """---
license:
- cc-by-4.0
- isc
pretty_name: ctbench
size_categories:
- n<1K
task_categories:
- text-classification
tags:
- hardware
- verilog
- rtl
- constant-time
- side-channel
- formal-verification
- security
configs:
- config_name: default
  data_files:
  - split: test
    path: corpus.jsonl
---

# ctbench

**A constant-time hardware benchmark where every safe design ships beside a
deliberately leaky twin with an identical interface — so a tool is graded against
controls instead of against itself.**

## What this is

{n_scored} scored Verilog fixtures across {n_pairs} matched pairs, plus {n_unscored}
unscored files retained for context. Each pair is two designs that differ in exactly
one thing: whether the cycle at which the completion signal asserts depends on a
secret operand. Same ports, same widths, same interface.

A tool earns a pair only by calling the safe one safe **and** the leaky one leaky.
That single constraint kills the two degenerate strategies — always answer `LEAKY`,
or always answer `CONSTANT_TIME` — that any single-verdict corpus rewards.

## The out-of-remit control

`barrett_buggy.v` is genuinely constant-time and **functionally wrong**: a
miscalibrated Barrett shift makes 62,206 of 65,536 coefficients disagree with the
reference. A timing tool that flags it is crying wolf, because functional
incorrectness is not a timing channel. It is labelled `out_of_remit` and exists to
separate serious tools from pattern-matchers.

## Fields

| Field | Meaning |
|---|---|
| `file` | fixture file name |
| `module` | top-level module name |
| `source` | complete Verilog-2001 source |
| `scored` | whether the fixture is part of the graded task |
| `label` | `CONSTANT_TIME`, `LEAKY`, or `null` for unscored |
| `observation` | completion signal the verdict is about |
| `secrets` | inputs declared secret; **never inferred** |
| `pair` | matched-pair group, if any |
| `role` | `positive`, `negative`, `repaired`, or `out_of_remit` |
| `note` | what the fixture demonstrates |
| `reason` | why an unscored fixture is unscored |
| `license` | `CC-BY-4.0`, or `ISC` for the picorv32 derivatives |

## Usage

```python
from datasets import load_dataset

ds = load_dataset("nickh007/hw-verify", "rtl_constant_time", split="test")
scored = ds.filter(lambda r: r["scored"])
print(scored[0]["module"], scored[0]["label"])
```

## Scoring

Do not score this with plain accuracy. The two error directions are not equally bad,
and the reference implementation ranks accordingly:

* **unsound** — said safe, is leaky. Ships a vulnerability. Dominates the ranking.
* **imprecise** — said leaky, is safe. Costs engineering time.
* **abstained** — returned `UNKNOWN`. Neither correct nor unsound.

`pip install ctbench` gives you `ctbench score`, `ctbench validate`, and
`ctbench leaderboard`, which implement exactly this rule.

## Scope

Labels concern **completion timing** with respect to the declared secrets — not
power, EM, cache, or microarchitectural channels. Secrets are a specification
choice recorded per fixture, never inferred from the source.

## Licence

RTL fixtures are **CC-BY-4.0**, except `pcpi_div.v`, `pcpi_mul.v`,
`pcpi_div_wiped.v` and `pcpi_div_halfwipe.v`, which derive from the picorv32
project by Claire Wolf and remain under the upstream **ISC** licence. The `license`
field on every record carries the correct one.
"""


def build_records(manifest: dict | None = None, fixtures: Path | None = None) -> list[dict]:
    """One record per fixture, with the source inlined."""
    man = manifest or load_manifest()
    root = fixtures or (Path(__file__).resolve().parent / "fixtures")

    def record(e: dict, scored: bool) -> dict[str, Any]:
        return {
            "file": e["file"],
            "module": e["module"],
            "source": (root / e["file"]).read_text(),
            "scored": scored,
            "label": e["expected"] if scored else None,
            "observation": e["observation"] if scored else None,
            "secrets": e["secrets"] if scored else [],
            "pair": e.get("pair") if scored else None,
            "role": e.get("role") if scored else None,
            "note": e.get("note", "") if scored else "",
            "reason": None if scored else e["reason"],
            "license": "ISC" if e["file"] in ISC_FIXTURES else "CC-BY-4.0",
        }

    records: list[dict[str, Any]] = [record(e, True) for e in man["scored"]]
    records += [record(e, False) for e in man["unscored"]]
    return records


def render_card(records: list[dict]) -> str:
    scored = [r for r in records if r["scored"]]
    pairs = {r["pair"] for r in scored if r["pair"]}
    return CARD.format(
        n_scored=len(scored),
        n_pairs=len(pairs),
        n_unscored=len(records) - len(scored),
    )


def export(out_dir: Path | str, manifest: dict | None = None) -> dict[str, Any]:
    """Write `corpus.jsonl` and `README.md` (the dataset card) into `out_dir`."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    records = build_records(manifest)

    jsonl = out / "corpus.jsonl"
    with jsonl.open("w") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    (out / "README.md").write_text(render_card(records))

    return {
        "directory": str(out),
        "records": len(records),
        "scored": sum(1 for r in records if r["scored"]),
        "files": ["corpus.jsonl", "README.md"],
    }
