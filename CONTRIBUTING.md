# Contributing

The most valuable contribution is **a fixture we get wrong** — especially one where we
report `CONSTANT_TIME` and you can demonstrate a leak. That is a soundness bug, it is
the one class of defect this project cannot tolerate, and finding one is worth more
than any feature.

## Ways to help, roughly by value

1. **A design we misjudge.** Open an issue with the module, the observation signal, the
   declared secrets, and why you believe the verdict is wrong. Unsound (we said safe,
   it leaks) is urgent; imprecise (we said leaky, the path is dead) is still valuable.
2. **A new matched pair for the corpus.** A safe design and a leaky twin with an
   *identical interface*, so the pair cannot be won by guessing. See below.
3. **A frontend.** FIRRTL, a different netlist format, SystemVerilog. One function
   returning a `Module`, plus a differential test against an existing frontend.
4. **Cell semantics.** The netlist reader refuses unmodelled cell types; adding one
   means adding it to the table in `netlist.py` *and* a test that its edges are right.
5. **Docs.** If something was confusing, that is a bug in the docs, and the fix is
   welcome.

## Adding a fixture

```
ctbench/fixtures/my_thing.v          the design
ctbench/fixtures/my_thing_leaky.v    its twin, identical interface
ctbench/fixtures/manifest.json       the entry: observation, secrets, expected, pair
```

Requirements:

- **Both halves of a pair, or neither.** A lone safe design can be passed by a tool
  that calls everything safe.
- **Comment what makes it leak**, in the file. The corpus is read by humans.
- **State the licence** if it derives from existing RTL. Four fixtures derive from
  picorv32 and remain ISC; the rest are CC-BY-4.0.
- Run `ctbench run` and confirm the reference checker gets it right, or explain why it
  should not.

## Running everything

```bash
pip install -e ".[dev]"
pytest tests -q          # 225 tests
ruff check .
```

Yosys is optional; the netlist differential tests skip without it and run in CI.

## What a change has to preserve

These are invariants, not preferences. `ARCHITECTURE.md` explains why.

- **`UNKNOWN` outranks `LEAKY`** everywhere they are compared.
- **`constant_time` is `True` only for `CONSTANT_TIME`.**
- **Every new failure mode subclasses `AnalysisRefused`**, or `check` will not catch
  it and junk input becomes a traceback instead of a verdict.
- **Optimisations may not change an answer** — add a test comparing the fast path
  against the slow one over the whole corpus.
- **Secrets are never inferred.** No default, no heuristic.
- **No number in a doc that the code cannot reproduce.** `test_docs.py` enforces the
  parts it can.

## Tone of the tests

Tests are named for the property they defend and grouped by that property rather than
by the function they call. A test whose name is `test_check_works` tells a future
reader nothing; `test_a_baselined_unknown_never_becomes_constant_time` tells them what
breaks if it fails.

If you find a bug, add the test *first* and watch it fail. Several tests here exist
because a bug was found that way and would not have been found by reasoning.

## Reporting a security issue

If you believe a soundness bug has security impact for a real deployment, please open
a normal issue anyway — these are analysis tools, not a deployed service, and a public
fixture is how it gets fixed. Do **not** include third-party proprietary RTL.
