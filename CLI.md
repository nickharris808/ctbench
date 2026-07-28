# CLI and API reference

Everything the tool exposes. `ctbench --help` and `ctbench <command> --help` print
the same information more briefly.

---

## Commands

### `ctbench check FILE... [options]`

Check one or more Verilog files. Accepts paths, or bare names of bundled fixtures
(which resolve against the installed package from any directory).

| Option | Meaning |
|---|---|
| `--observation NAME` | the completion signal. Default: the manifest entry for a bundled fixture, else `done` |
| `--secret NAME` | a secret input. **Repeatable.** Required unless the file is a bundled fixture |
| `--module NAME` | which module in a multi-module file. Default: the first |
| `--json` | emit JSON — an object for one file, a list for several |
| `--sarif` | emit SARIF 2.1.0 for GitHub code scanning |
| `--netlist JSON` | analyse a Yosys JSON netlist instead of Verilog source |
| `--top NAME` | top module in the netlist (default: whichever Yosys marked) |
| `--baseline FILE` | accept the findings in FILE; fail only on new ones |
| `--update-baseline` | write current findings to the baseline and exit 0 |

Exit: `0` all constant-time · `1` at least one leaky · `2` at least one UNKNOWN.
Exit 2 outranks exit 1, so a job guarding only against `1` cannot be satisfied by
"we could not tell".

```bash
ctbench check cmp_leaky.v                                  # bundled fixture
ctbench check --netlist build/aes.json --secret key        # hierarchical design
ctbench check rtl/*.v --secret key --secret nonce          # your RTL, many files
ctbench check rtl/*.v --secret key --sarif > out.sarif     # for code scanning
```

### `ctbench fixtures`

List all 27 bundled fixtures with their expected verdicts and scored/unscored status.

### `ctbench run [--json]`

Run the bundled reference checker over every scored fixture and show each verdict
against what was expected.

### `ctbench score [SUBMISSION] [--json]`

Score a submission — a JSON map of fixture name to verdict — against the corpus.
With no argument, scores the bundled reference checker. Exit `0` only if the
submission is **sound**; imprecision alone does not fail.

### `ctbench submit [--verdicts F] --tool NAME --tool-version V [-o OUT]`

Wrap a set of verdicts in a submission payload, validating it before writing.

### `ctbench validate SUBMISSION`

Check a submission is well formed — covers every scored fixture, invents no fixture
names, uses only the permitted verdict vocabulary — then score it.

### `ctbench leaderboard [--json] [--path DIR]`

Render the leaderboard from the submission registry. Ranking is lexicographic:
`(sound, pairs_separated, correct, -imprecise, -abstained)`.

### `ctbench export --out DIR`

Emit the corpus as JSONL plus a dataset card, loadable by `datasets`.

---

## Python API

```python
from ctbench import check, analyse, UNKNOWN, CONSTANT_TIME, LEAKY
from ctbench import check_netlist, load_netlist, Findings

v = check(source, "done", ["key", "nonce"], module_name=None)
v.status          # "CONSTANT_TIME" | "LEAKY" | "UNKNOWN"
v.constant_time   # True only for a positively established CONSTANT_TIME verdict
v.reaching        # secrets found in the cone, sorted
v.cone_size       # size of the fan-in cone (a sanity check, not a score)
v.reason          # why no verdict was reached; None unless status is UNKNOWN
v.to_dict()       # JSON-shaped
```

**`check` vs `analyse`.** They do the same analysis and differ only in how they
report a refusal:

- `analyse(...)` **raises** — `UnsupportedConstruct`, `UndrivenObservation`,
  `UnknownObservation`, `ModuleNotFound`, `NoModuleFound`, all subclasses of
  `AnalysisRefused`. Use it when a refusal should stop the program.
- `check(...)` **returns** a Verdict with `status == UNKNOWN` and a populated
  `reason`. Use it when you must report on every input — a CLI over many files, CI,
  an agent — and one unreadable file should not abort the run.

`v.constant_time` is `False` for `UNKNOWN`, so code written as
`if v.constant_time: ship()` stays correct without knowing about the third state.

### Other entry points

```python
from ctbench.cone import unsupported_constructs, parse
unsupported_constructs(src)   # [(construct, line, snippet), ...] — empty if analysable
parse(src, module_name)       # -> Module with .inputs, .outputs, .deps, .cone(roots)

from ctbench import Findings          # a result set, and every output format
f = Findings(); f.add(verdict, "rtl/a.v")
f.to_json(); f.to_sarif(); f.to_table(); f.exit_code()   # UNKNOWN outranks LEAKY

from ctbench import check_netlist     # the Yosys frontend, same Verdict type
from ctbench.baseline import Baseline # accept known findings

from ctbench.score import score, load_manifest, format_report
from ctbench.sarif import to_sarif          # verdict dicts -> SARIF 2.1.0 log
from ctbench.leaderboard import build_leaderboard, parse_submission
```

---

## SARIF rules

| Rule | Level | Fires when |
|---|---|---|
| `CT001` | error | a declared secret reaches the observation signal |
| `CT002` | warning | no verdict was reached — the file was **not** checked |

`CT002` exists because silence in a SARIF report is indistinguishable from a clean
pass. Clean files produce no result but are listed in `runs[].artifacts`, so
"checked and clean" stays distinguishable from "never looked at".

---

See [SCOPE.md](SCOPE.md) for what a verdict means, [TUTORIAL.md](TUTORIAL.md) for the
workflow, and [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for errors.
