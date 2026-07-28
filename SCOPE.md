# Honest scope — what a ctbench verdict does and does not mean

Read this before quoting a `CONSTANT_TIME` verdict at anyone. It is short, and every
limit in it is real.

---

## The claim, stated precisely

A `CONSTANT_TIME` verdict says:

> Within the supported Verilog subset, no signal you declared secret appears in the
> syntactic fan-in cone of the signal you named as the observation — including
> through any enclosing `if` or `case` guard.

That is all it says. Everything below is a way of not over-reading it.

---

## What it proves

- **Completion timing is not a function of the declared secrets.** If no secret is in
  the fan-in cone, the observation signal cannot depend on one, so the cycle it
  asserts on is data-oblivious with respect to those inputs.
- **Guard conditions are included.** In `if (xr != yr) running <= 1'b0;`, `running`
  does not syntactically receive `xr` or `yr`, but its value depends on both. Every
  enclosing condition is an edge into everything assigned beneath it. Missing this is
  the most common way a hand-rolled fan-in check goes wrong.
- **A `LEAKY` verdict names the reaching signals**, so you can confirm the finding
  rather than take it on faith.

## What it does **not** prove

- **Nothing about power, EM, cache, or microarchitectural channels.** This is a
  timing analysis. A `CONSTANT_TIME` design can leak catastrophically through power.
- **Nothing about secrets you did not declare.** Secrets are a specification choice
  and are never inferred. Declare the wrong set and you get a confident verdict about
  the wrong property.
- **Nothing about functional correctness.** The corpus deliberately contains
  `barrett_buggy.v`, which is genuinely constant-time *and* computes the wrong
  answer. Both facts are true at once.
- **Nothing about the design after synthesis.** The analysis reads RTL. A synthesis
  tool is free to introduce a data-dependent optimisation the RTL did not have.
- **Nothing outside the supported subset** — see below.

---

## The supported subset

The analysis reads **one flat module**, consisting of:

- `assign` statements;
- net declarations carrying an initialiser (`wire done_now = running && ...;`);
- `always` blocks containing `if` / `else` / `case` / `casez` / `casex` and blocking
  or non-blocking assignments.

## What is refused, and why refusing is the point

These constructs return **`UNKNOWN`**, never a verdict:

| Construct | Why it cannot be read |
|---|---|
| module instantiation | the submodule body is not analysed, so every edge through it is invisible |
| `for` loop | the loop body's dependencies are not unrolled |
| `generate` block | same, plus the elaboration is not performed |
| `function` / `task` definition | the body is not inlined into its call sites |
| `while`, `repeat`, `forever` | loop bodies are not analysed |
| preprocessor directives (`` `define ``, `` `ifdef ``) | a macro can hide an entire guard expression behind one token |

The reason this is a refusal and not a warning is worth understanding, because it is
the single most important property of the tool:

> A construct the parser skips is not a *little* imprecision. It deletes dependency
> edges. A signal with no edges has an empty fan-in cone. An empty cone contains no
> secrets. And no secrets reads as **safe**.

So partial analysis of a design containing one of these does not produce a vaguer
answer — it produces a confident *wrong* one, in the dangerous direction. The tool
declines instead, names the construct and the line, and exits 2.

**`UNKNOWN` is not a pass.** It exits non-zero, `constant_time` is `False` for it,
the GitHub Action counts it separately from `checked`, and SARIF reports it as a
warning rather than omitting it.

Two other refusals in the same spirit:

- an observation declared as an output but driven by nothing the parser read
  (`UndrivenObservation`) — an empty cone that would otherwise read as safe;
- an observation that is not a signal of the module at all (`UnknownObservation`),
  which names the declared outputs so you can spot the typo.

---

## Where it is imprecise, and in which direction

Within the supported subset the analysis is a **syntactic over-approximation**. It
follows every path in the dependency graph, whether or not that path can be taken at
run time. So:

- **`LEAKY` may be pessimistic.** A secret can reach the observation through a
  branch that is provably never taken, and the analysis will still flag it. That is
  why a `LEAKY` verdict names the signals: it is an invitation to check, not a
  conviction.
- **`CONSTANT_TIME` is conservative *within the subset*.** Over-approximating means
  extra edges, never missing ones, so if no secret is in the cone none can be.

That qualifier is doing real work. Outside the subset the analysis is not
conservative and not sound — which is precisely why it refuses rather than guessing.

The bundled reference checker scores 18/18 on the corpus and separates all 8 matched
pairs. **This is a baseline, not a strong tool**: it reasons about syntax, not
semantics, and it exists mostly to make the benchmark self-demonstrating.

---

## Proving this to someone who cannot see your RTL

Every tool here analyses a design **you hand it in full**. If you need an integrator,
an auditor, or a customer to believe a verdict *without receiving your netlist*, that
requires the result bound to a commitment of a design that is never disclosed. That
is a different problem and a commercial one. It is not in this package, and nothing
here implements a commitment scheme, an attestation, or a confidential verification
path.

---

## Sibling tools

- [`ct-mask`](https://github.com/nickharris808/ct-mask) — masking countermeasures,
  where the property is share independence rather than timing.
- [`patchproof`](https://github.com/nickharris808/patchproof) — bounds-check fixes,
  where the question is whether *every* violating input is eliminated.
- [`ct-audit-action`](https://github.com/nickharris808/ct-audit-action) — this
  analysis on every pull request.
- [`hw-verify-mcp`](https://github.com/nickharris808/hw-verify-mcp) — all three,
  callable by an AI agent that cannot mark its own homework.
