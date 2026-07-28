# Contributing to ctbench

The most valuable contribution is **a new matched pair**.

## What makes a good pair

A pair is two designs that differ in exactly one thing: whether completion timing depends
on a secret. Both halves must have an **identical module interface** — same ports, same
widths, same parameters. If a tool can tell them apart by looking at the port list, the
pair does not test anything.

Include a header comment on each file saying what the leak is and where. A fixture whose
leak nobody can explain is not a benchmark, it is a puzzle.

## Adding one

1. Drop both `.v` files in `ctbench/fixtures/`.
2. Add both to the `scored` array in `ctbench/fixtures/manifest.json` with a shared
   `pair` name and `role` of `positive` / `negative`, plus the `observation` signal and
   the `secrets` list.
3. Run `python -m pytest tests -q`. The suite checks that every pair has both roles, that
   every fixture on disk is listed, and that every `LEAKY` fixture actually names a
   reaching secret.
4. Regenerate the baseline and commit it:
   ```bash
   python -c "import json,platform,sys; sys.path.insert(0,'.'); \
     from ctbench.cli import run_reference; from ctbench.score import load_manifest, score; \
     m=load_manifest(); v=run_reference(m); \
     json.dump({'tool':'ctbench reference checker (syntactic cone-of-influence)', \
       'tool_version':'1.0.0','environment':{'python':platform.python_version()}, \
       'verdicts':v,'score':score(v,m).to_dict()}, open('baseline.json','w'), indent=2)"
   ```

The baseline is checked against a fresh run by the test suite, so it cannot silently drift.

## If the reference checker gets your pair wrong

That is a useful contribution too — open an issue with the pair. An over-approximate
checker is *expected* to report `LEAKY` on some safe designs. What it must never do is
report `CONSTANT_TIME` on a leaky one; that is a soundness bug and we treat it as such.

## Third-party RTL

If a fixture derives from an existing project, say so in the file header and add the
upstream licence to `LICENSE-FIXTURES`. Do not vendor code whose licence you have not read.

## Style

Fixtures: plain Verilog-2001, synthesisable subset, no vendor primitives.
Python: `ruff check .` clean, 100-column lines.
