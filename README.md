# ctbench

**A constant-time hardware benchmark where every safe design ships beside a deliberately leaky twin with an identical interface — so your tool is graded against controls instead of against itself.**

[![License](https://img.shields.io/badge/harness-Apache--2.0-blue.svg)](LICENSE)
[![Fixtures](https://img.shields.io/badge/fixtures-CC--BY--4.0-lightgrey.svg)](LICENSE-FIXTURES)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![CI](https://github.com/nickharris808/ctbench/actions/workflows/ci.yml/badge.svg)](https://github.com/nickharris808/ctbench/actions/workflows/ci.yml)

> **▶ [Try it in your browser](https://huggingface.co/spaces/nickh007/hw-verify)** — paste Verilog, get a formal constant-time verdict with the leaking signals named. No install, nothing uploaded.


## Why this exists

Constant-time hardware analysis has no standard benchmark. Every tool reports its own
accuracy on its own examples, so "we detect timing leaks" is unfalsifiable — a tool that
returns `LEAKY` for everything scores 100% on a corpus of leaky designs.

ctbench fixes the methodology rather than the tools. Each fixture is one half of a
**matched pair**: `ct_cmp` (always scans all bits) sits beside `cmp_leaky` (early-exit
memcmp) with the *same module interface*, the same ports, the same widths. A tool only
earns credit for a pair when it calls the safe one safe *and* the leaky one leaky. That
single constraint kills both degenerate strategies at once.

There is also an **out-of-remit control**. `barrett_buggy` is genuinely constant-time and
*functionally wrong* — a miscalibrated shift makes 62,206 of 65,536 coefficients incorrect.
A timing tool that flags it is crying wolf: functional incorrectness is not a timing
channel. That fixture exists because our own analysis initially misclassified it.

## Install

> **Not yet on PyPI.** Install from a checkout:

```bash
git clone https://github.com/nickharris808/ctbench.git && cd ctbench
pip install .
```

Once published, this becomes `pip install ctbench`.

## 30-second quickstart

```bash
# Run the bundled reference checker over the whole corpus and score it
ctbench score

# Check a bundled fixture by name (secrets come from the manifest)
ctbench check cmp_leaky.v

# Check a design of your own
ctbench check my_core.v --observation done --secret key --secret nonce

# Check a whole directory at once
ctbench check rtl/*.v --secret key --secret nonce

# Emit SARIF 2.1.0 so findings land in GitHub code scanning
ctbench check rtl/*.v --secret key --sarif > ctbench.sarif

# Hierarchical design? Analyse the synthesised netlist instead
yosys -q -p 'read_verilog rtl/*.v; hierarchy -top aes_core; proc; flatten; \
             opt_clean; write_json build/aes.json'
ctbench check --netlist build/aes.json --secret key

# Adopting on an existing codebase: accept what is there, fail only on new findings
ctbench check rtl/*.v --secret key --baseline ctbench-baseline.json --update-baseline
ctbench check rtl/*.v --secret key --baseline ctbench-baseline.json

# Where do the bundled fixtures live?
ctbench fixtures
```

## Worked example

```console
$ ctbench score
ctbench scorecard
====================================================
  fixtures scored     18/18  (100.0%)
  pairs separated     8/8
  sound               YES
  out-of-remit ctrl   PASS
```

Checking one file, and what a leak report looks like:

```console
$ ctbench check cmp_leaky.v
{
  "module": "cmp_leaky",
  "observation": "done",
  "secrets": [
    "x",
    "y"
  ],
  "reaching_secrets": [
    "x",
    "y"
  ],
  "verdict": "LEAKY",
  "cone_size": 9
}
```

Exit status is `0` for `CONSTANT_TIME` and `1` for `LEAKY`, so it drops into CI directly.

## Scoring your own tool

Emit a JSON object mapping fixture file name to `CONSTANT_TIME`, `LEAKY`, or `UNKNOWN`:

```json
{ "ct_cmp.v": "CONSTANT_TIME", "cmp_leaky.v": "LEAKY", "barrett_buggy.v": "CONSTANT_TIME" }
```

```bash
ctbench score my_submission.json
```

The scoring is deliberately asymmetric, because the two error directions are not equally bad:

| Outcome | Meaning | Treated as |
|---|---|---|
| **Unsound** | said safe, is leaky | reported first; fails the run (exit 1) |
| **Imprecise** | said leaky, is safe | reported, does not fail the run |
| **Abstained** | returned `UNKNOWN` | neither correct nor unsound |

Abstention is not punished as hard as being wrong. A tool that admits it cannot decide is
more useful than one that guesses.

## What it reads, and what it refuses

The analysis reads **one flat module** of `assign` statements, net declarations carrying
an initialiser, and `always` blocks. That is the whole supported subset.

Anything else — a **submodule instantiation**, a `for` loop, `generate`, a `function` or
`task` definition, a preprocessor macro — is *not* partially analysed. Each of those
creates dependency edges the cone cannot follow, and a missing edge does not make the
answer vaguer: it empties the cone, and an empty cone contains no secrets, and no secrets
reads as safe. Analysing the readable remainder of such a design would report
`CONSTANT_TIME` for a design that genuinely leaks.

So the checker refuses. Out-of-subset constructs return **`UNKNOWN`**, naming the
construct and the line, and an observation that nothing in the parsed source drives
returns `UNKNOWN` rather than a vacuous pass.

**`UNKNOWN` is not a pass.** It is the absence of a verdict, it exits non-zero, and
`constant_time` is `False` for it.

## The leaderboard

A corpus is only a benchmark if others can submit to it and be ranked by a rule they did
not choose. That rule is **lexicographic, and soundness comes first**:

```
(sound, pairs_separated, correct, -imprecise, -abstained)
```

A tool that reports one leaky design as safe ranks **below every sound tool**, however
accurate it is otherwise. Within the sound tools, separating matched pairs counts for more
than raw accuracy, because a pair is the only evidence a tool is discriminating rather than
guessing a constant.

```bash
ctbench submit --tool my-checker --tool-version 1.2 --verdicts my.json -o sub.json
ctbench validate sub.json          # complete? well formed? in the vocabulary?
ctbench leaderboard submissions/   # ranked Markdown table
```

```console
$ ctbench leaderboard submissions/
| # | Tool | Sound | Pairs | Correct | Imprecise | Abstained | Control |
|---|---|---|---|---|---|---|---|
| 1 | [ctbench-reference 1.0.0](https://github.com/nickharris808/ctbench) | yes | 8/8 | 18/18 | 0 | 0 | pass |
| 2 | naive-syntactic 0.1 | **NO** | 7/8 | 16/18 | 1 | 0 | **wolf** |
```

`naive-syntactic` is a straw tool shipped in `submissions/` to show what the ranking
penalises: it calls one leaky design safe (**unsound**) and cries wolf on the out-of-remit
control.

**Submissions are validated before scoring.** One that omits fixtures, invents names, or
uses verdicts outside the vocabulary is rejected with a reason rather than partially
credited — otherwise the cheapest route up the board is to answer only the easy half. To
decline a fixture, answer `UNKNOWN`; that is tracked, and ranks above being wrong.

## As a Hugging Face dataset

```bash
ctbench export hf-dataset/     # corpus.jsonl + a dataset card
```

Emits one record per fixture with the full Verilog source inlined, loadable directly:

```python
from datasets import load_dataset
ds = load_dataset("json", data_files="hf-dataset/corpus.jsonl", split="train")
```

The licence is **per record**: the four picorv32 derivatives carry `ISC`, everything else
`CC-BY-4.0`. Flattening that to one dataset-level licence would misstate it.

## What is in the corpus

27 Verilog fixtures: **18 scored** across 8 matched pairs plus a repaired variant and the
out-of-remit control, and **9 unscored** (documented in `ctbench/fixtures/manifest.json`
with the reason for each). The unscored files are fault-detection and secret-residue
fixtures whose observable is a data output rather than a completion signal — grading them
under the constant-time task would be a category error, so they are reserved for future
tasks rather than quietly counted.

Scored pairs: `barrett` · `cmp` · `div` · `gcd` · `modmul` · `mul` · `modexp` · `x25519`.

## The bundled reference checker

The baseline in `baseline.json` is produced by a **syntactic cone-of-influence checker**:
it takes the fan-in cone of the observation signal — including every enclosing `if`/`case`
guard condition, which is the part naive implementations miss — and intersects it with the
declared secret inputs.

Within the supported subset below it is an over-approximation, so `CONSTANT_TIME` is
conservative there and `LEAKY` names the reaching signals; outside that subset it returns
`UNKNOWN` rather than a verdict. It scores 18/18 on this corpus. **This is a baseline, not a strong
tool**: it reasons about syntax, not semantics, and will over-report on designs where a
secret reaches a completion signal through a path that is provably never taken.

## Scope and honest limits

- Verdicts concern **completion timing** with respect to declared secrets, not power, EM,
  cache, or microarchitectural channels.
- The reference checker parses a **synthesisable Verilog-2001 subset**. It is not a
  general Verilog front end.
- Secrets are **declared**, never inferred. Which inputs are secret is a specification
  choice, and the manifest records it per fixture.

## Proving this to someone who cannot see your netlist

ctbench grades tools that analyse RTL **you hand them**. If you need a third party — an
integrator, an auditor, a customer — to believe a constant-time result *without receiving
your netlist*, that is a different problem: it needs a proof that binds to a commitment of
a design that is never disclosed. That capability is commercial and is not part of this
package. Everything here operates on designs you already control.

## Hierarchical designs: the netlist frontend

The source parser reads one flat module and refuses everything else, which is correct
and, on real designs, frustrating — production RTL has submodules, so the honest
answer is usually `UNKNOWN`.

Point it at a synthesised netlist instead:

```bash
yosys -q -p 'read_verilog rtl/*.v; hierarchy -top aes_core; proc; flatten; \
             opt_clean; write_json build/aes.json'
ctbench check --netlist build/aes.json --observation done --secret key
```

After `flatten` the constructs the source parser refuses no longer exist: `generate`
and `for` have been unrolled, `function` inlined, macros expanded, and the hierarchy
collapsed into one cell graph. So the netlist path answers exactly the designs the
source path has to decline.

**The two frontends agree.** They share the same cone analysis, and a test synthesises
every scored fixture and asserts both paths reach the same verdict — a divergence
would mean one of them is wrong, and we would not know which.

**Refusal is stricter here, not looser.** A netlist is a graph of cells; an unmodelled
cell means missing dependency edges, and a missing edge is how a leaky design comes
back clean. So an unrecognised cell type is refused by name, and a blackbox that
survived flattening says so. Yosys is never invoked for you — you run it, and the
JSON is an explicit input.

## Adopting on an existing codebase

Day one on an existing repo shows every finding at once, which is how a new check
gets switched off. Record what is already there, then fail only on what is new:

```bash
ctbench check rtl/*.v --secret key --baseline ctbench-baseline.json --update-baseline
git add ctbench-baseline.json
```

A baseline entry matches one exact finding — file, module, observation, verdict, and
the precise set of reaching secrets. **A different leak in an already-baselined file
is still reported**, because suppressing by filename would quietly hide the next bug
in every file anyone ever accepted.

A baselined `UNKNOWN` is excluded from the exit code but is **never rewritten to
`CONSTANT_TIME`**: it still prints as `UNKNOWN`, still counts as `UNKNOWN`, and still
exports as `UNKNOWN`. Acknowledging that no verdict was reached is not the same as
reaching one.

## Three verdicts, three exit codes

| Exit | Verdict | Meaning |
|---|---|---|
| `0` | `CONSTANT_TIME` | no declared secret reaches the observation signal |
| `1` | `LEAKY` | one does, and the reaching signals are named |
| `2` | `UNKNOWN` | the analysis could not read the design. **No verdict.** |

Exit 2 deliberately outranks exit 1 when several files are checked: a job guarding
only against `1` must not be satisfied by "we could not tell". `UNKNOWN` is not a
pass — see [SCOPE.md](SCOPE.md) for the constructs that produce it and why refusing
is the sound behaviour.

## Documentation

| | |
|---|---|
| [TUTORIAL.md](TUTORIAL.md) | end to end: find a leak, fix it, put the check in CI |
| [SCOPE.md](SCOPE.md) | what a verdict proves — and the constructs it refuses, and why |
| [CLI.md](CLI.md) | every command, flag, exit code, and the Python API |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | every error message, what it means, what to do |

<!-- portfolio:start -->
## Part of the hw-verify toolkit

Open tools for proving security properties of hardware and bounds checks.
They share one boundary: **everything open analyses a design you disclose in full.**

| Project | What it does |
|---|---|
| **▶ [Live demo](https://huggingface.co/spaces/nickh007/hw-verify)** | Constant-time checker in your browser — the real analyzer via Pyodide |
| [**Docs & overview**](https://huggingface.co/spaces/nickh007/hw-verify-site) | What the toolkit proves, and what it refuses to answer |
| [`hw-verify`](https://github.com/nickharris808/hw-verify) | One install, one command, all three checkers |
| **`ctbench`** (you are here) | Matched-pair constant-time RTL benchmark + [leaderboard](https://github.com/nickharris808/ctbench#the-leaderboard) |
| [`patchproof`](https://github.com/nickharris808/patchproof) | Prove a bounds-check fix eliminates *every* violating input |
| [`patchproof-verify`](https://github.com/nickharris808/patchproof-verify) | Re-check its certificates in Rust, with no shared code |
| [`ct-mask`](https://github.com/nickharris808/ct-mask) | First-order masking verification by two certificates |
| [`hw-verify-mcp`](https://github.com/nickharris808/hw-verify-mcp) | MCP server — the checkers, callable by AI agents |
| [`ct-audit-action`](https://github.com/nickharris808/ct-audit-action) | GitHub Action — fail a PR on a leaky completion signal |
| [verdicts](https://huggingface.co/datasets/nickh007/hw-verify) · [witness paths](https://huggingface.co/datasets/nickh007/hw-verify-paths) | Two datasets: what each design is, and why |

**The commercial boundary.** Proving a property to a third party who never receives
the design — a verdict bound to a commitment of a design that stays hidden — is a
different problem and a commercial one. It is not in any of these packages.
<!-- portfolio:end -->

## Citation

If you use this in academic work, please cite it — [CITATION.cff](CITATION.cff) has
the metadata, and GitHub renders a "Cite this repository" button from it.

## Contributing

The most valuable contribution is **a fixture we get wrong**. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Harness: Apache-2.0 (`LICENSE`). RTL fixtures: CC-BY-4.0, except four picorv32-derived
fixtures which remain under the upstream ISC License — see [`LICENSE-FIXTURES`](LICENSE-FIXTURES)
for full attribution.

## Contributing

New matched pairs are the most valuable contribution. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Pre-commit hook

The tightest feedback loop: run on the files that changed, at commit time, before CI
ever sees them.

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/nickharris808/ctbench
    rev: main            # or pin a tag
    hooks:
      - id: ctbench
        args: [--secret, key, --secret, nonce]
```

Secrets are still never inferred, so `args` is required — a hook that guessed which
inputs were sensitive would give confident verdicts about the wrong property on every
commit.
