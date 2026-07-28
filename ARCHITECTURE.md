# Architecture

How ctbench actually works, why the refusal design is what it is, and where to add
things. Written for someone about to change the code.

---

## The whole analysis in one paragraph

Parse a design into a **dependency graph**: signal → the set of signals it depends on.
Take the transitive fan-in closure of the observation signal. Intersect with the
declared secrets. Non-empty means `LEAKY`; empty means `CONSTANT_TIME`. That is the
entire idea, and it fits in `cone.py`.

Everything else in the codebase exists because of two facts: *guards are dependencies*,
and *what you cannot read, you must not answer about*.

## Guards are dependencies

```verilog
if (xr != yr) running <= 1'b0;
```

`running` never syntactically receives `xr`, but its value depends on both operands.
So every enclosing `if`/`case` condition becomes an edge into everything assigned
beneath it. Missing this is the most common way a hand-rolled fan-in check goes wrong,
and it is why `_walk` tracks a `guards` set as it descends.

## Two frontends, one core

```
Verilog source ──► parse()          ─┐
                                     ├─► Module ──► verdict_for() ──► Verdict
Yosys JSON     ──► parse_netlist()  ─┘
```

`verdict_for` holds the undriven/unknown-observation refusals, the cone walk, and the
secret intersection. Both frontends produce a `Module` and nothing else.

That split is what makes the differential test meaningful: `test_netlist.py`
synthesises every scored fixture with Yosys and asserts both paths reach the same
verdict. Since they share everything after parsing, a divergence has to come from the
parsing — and a divergence means one of them is wrong.

**Adding a third frontend** (FIRRTL, a different netlist format) means writing one
function that returns a `Module`, plus a differential test against an existing
frontend. Do not add analysis logic to a frontend.

## Why refusal, and why it is structural

A parser that skips what it does not understand seems conservative and is the
opposite. Skipping deletes edges. A signal with no edges has an empty cone. An empty
cone contains no secrets. No secrets reads as **safe**.

So the refusals are not error handling, they are the safety argument:

| Refusal | Fires when |
|---|---|
| `UnsupportedConstruct` | source contains a construct the parser cannot follow |
| `UndrivenObservation` | the observation is declared but nothing read drives it |
| `UnknownObservation` | the observation is not a signal of the module |
| `ModuleNotFound` / `NoModuleFound` | the named module, or any module, is absent |
| `UnknownCell` | a netlist cell type with no modelled semantics |
| `UndirectedPort` | a connected cell port with no declared direction |
| `NetlistError` | the netlist is malformed in any other way |

All subclass `AnalysisRefused`. `analyse` raises them; `check` converts them to an
`UNKNOWN` verdict. **Any new failure mode must subclass `AnalysisRefused`**, or `check`
will not catch it and junk input will surface as a traceback instead of a verdict.
Three bugs of exactly that shape were found by the stress suite.

## Module map

| File | Responsibility |
|---|---|
| `cone.py` | the graph, the cone walk, `verdict_for`, every refusal type, the RTL parser |
| `netlist.py` | the Yosys JSON frontend, and the cell-semantics table |
| `findings.py` | a result set, every output format, and the exit-code policy |
| `explain.py` | witness paths (BFS shortest, bounded enumeration for more) |
| `diff.py` | classifying what changed between two runs |
| `baseline.py` | accepting known findings without hiding new ones |
| `sarif.py` | SARIF 2.1.0 for GitHub code scanning |
| `score.py` / `leaderboard.py` | benchmark scoring and ranking |
| `cli.py` | argument parsing and delegation only — no analysis |

`Findings` owns every emitter deliberately. Before it existed each output format grew
its own loop over the verdict list, and three copies of "what is the worst verdict"
would drift. **A new output format is a method on `Findings`**, not a new loop.

## Invariants a change must not break

1. **`UNKNOWN` outranks `LEAKY` everywhere they are compared.** A caller guarding only
   against "leaky" must not be satisfied by "we could not tell". This is `_SEVERITY`
   in `findings.py` and the exit-code ordering.
2. **`Verdict.constant_time` is `True` only for `CONSTANT_TIME`.** Code written as
   `if v.constant_time: ship()` must stay correct without knowing `UNKNOWN` exists.
3. **Optimisations may not change an answer.** The scanner pre-filter and ct-mask's
   fan-in pre-filter each have a test comparing them against an unfiltered oracle over
   the whole corpus. A speedup that changes a verdict is a bug with a stopwatch.
4. **Every reported path is a real path.** `explain` output is checked edge by edge
   against the graph.
5. **A baseline entry suppresses one exact finding.** Not a file, not a pattern.

## Performance shape

Linear in design size: ~4.6 µs/signal, so a 100 000-signal netlist is about half a
second. The construct scanner was 38 % of runtime until each pattern was gated behind a
plain substring test (3.4× on the scanner). There is no cache and no parallelism yet;
both are listed in the roadmap and neither is currently a bottleneck.

## Testing philosophy

Tests are grouped by the property they defend, not by the function they call:

- `test_refusal.py` — no unreadable input yields a confident verdict
- `test_stress.py` — malformed, enormous, and out-of-distribution input
- `test_optimisations.py` — the fast path agrees with the slow path
- `test_netlist.py` — the two frontends agree
- `test_docs.py` — the documentation describes the tool that exists

That last one is not bureaucracy: it caught three fabrications in a tutorial, including
an invented number and a paragraph of reasoning built on it.
