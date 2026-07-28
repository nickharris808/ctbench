# Tutorial — find a timing leak, fix it, and keep it fixed

End to end, from install to a CI check that blocks the regression. Every command
below is real and every output is what the tool actually prints; copy them in order.

You need Python 3.10+ and about ten minutes.

---

## 1. Install

ctbench is not on PyPI yet, so install from the repository:

```bash
pip install git+https://github.com/nickharris808/ctbench@main
```

Check it landed:

```console
$ ctbench fixtures | head -4
bundled fixtures (/usr/lib/python3.11/site-packages/ctbench/fixtures):

  barrett_ct.v               scored    expected CONSTANT_TIME
  barrett_leaky.v            scored    expected LEAKY
```

Those 27 files ship inside the package, so every example here works from any
directory without cloning anything.

---

## 2. See a leak

`cmp_leaky.v` is a tag comparator that exits as soon as it finds a mismatch:

```verilog
always @(posedge clk) begin
    ...
    end else if (running) begin
        if (xr != yr) begin
            diff    <= 1'b1;
            running <= 1'b0;      // early exit: timing depends on the operands
        end
    end
end
```

Check it. Because it is a bundled fixture, the manifest already records which
signal is the completion signal and which inputs are secret, so you need not
retype them:

```console
$ ctbench check cmp_leaky.v
{
  "module": "cmp_leaky",
  "observation": "done",
  "secrets": ["x", "y"],
  "reaching_secrets": ["x", "y"],
  "verdict": "LEAKY",
  "cone_size": 9,
  "file": "cmp_leaky.v"
}
$ echo $?
1
```

`reaching_secrets` is the part that matters. The tool is not saying "something
looks wrong"; it is naming the two inputs whose values reach `done`, so you can
confirm the finding yourself rather than taking it on faith.

**Why is this a leak?** `done` asserts on the cycle the first mismatching bit is
found. An attacker who can time the comparison learns *where* the first difference
is, one byte at a time. That is enough to forge a tag.

---

## 3. See the fix

`ct_cmp.v` is the same interface, scanning all `W` bits every time:

```verilog
assign done = running & (cnt == W);   // cnt is a data-oblivious counter
```

```console
$ ctbench check ct_cmp.v
{
  "module": "ct_cmp",
  "observation": "done",
  ...
  "reaching_secrets": [],
  "verdict": "CONSTANT_TIME",
  "cone_size": 6,
  "file": "ct_cmp.v"
}
$ echo $?
0
```

`reaching_secrets` is now empty: no declared secret is anywhere in `done`'s fan-in.

Do not read too much into `cone_size` falling from 9 to 6. It is the size of the
fan-in cone, reported so you can sanity-check that the tool looked at a plausible
amount of logic — a cone of 1 or 2 on a real module usually means you named the
wrong signal. It is not a security score, and a *larger* cone is not worse. What
decides the verdict is whether a secret is in it, not how big it is.

These two files are a **matched pair**: same interface, same task, opposite verdict.
The corpus has eight such pairs, and a tool earns a pair only by getting both halves
right. Calling everything leaky scores zero.

---

## 4. Check your own RTL

Your design is not a bundled fixture, so name the completion signal and the secrets:

```console
$ ctbench check rtl/aes_core.v --observation done --secret key --secret nonce
```

Secrets are **never inferred**. Guessing which inputs are sensitive would produce
confident verdicts about the wrong property, so the tool refuses to guess and asks.

Several files at once:

```console
$ ctbench check rtl/*.v --secret key
  [LEAKY  ] rtl/cmp.v                                key
  [ok     ] rtl/ctr.v                                —
  [UNKNOWN] rtl/top.v                                no verdict
```

---

## 5. When it says UNKNOWN

Sooner or later you will hit this, because most real RTL is hierarchical:

```console
$ ctbench check rtl/top.v --observation done --secret key
{ ... "verdict": "UNKNOWN", "cone_size": 0, "reason": "line 5: module
  instantiation is outside the supported Verilog subset ..." }
$ echo $?
2
```

**This is the tool working, not failing.** The cone analysis reads one flat module
of `assign` statements and `always` blocks. A submodule instantiation creates
dependency edges it cannot follow — and a missing edge does not make the answer
vaguer, it empties the cone, and an empty cone contains no secrets, and no secrets
would read as *safe*. Rather than report a design it could not read as
constant-time, it declines and tells you which construct stopped it.

Exit code 2, distinct from 0 and 1, so CI cannot mistake it for a pass.

Two ways forward:

```bash
# analyse the submodule that actually drives the completion signal
ctbench check rtl/child.v --observation done --secret key

# or point at a flattened netlist, if your synthesis flow can emit one
ctbench check build/top_flat.v --observation done --secret key
```

See [SCOPE.md](SCOPE.md) for the full list of constructs that trigger this.

---

## 6. Put it in CI

The [ct-audit-action](https://github.com/nickharris808/ct-audit-action) wraps all
of the above:

```yaml
# .github/workflows/constant-time.yml
name: constant-time
on: [push, pull_request]
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: nickharris808/ct-audit-action@v1
        with:
          files: rtl/**/*.v
          secrets: key,nonce
```

Leaks become annotations on the diff and the job fails. Files that reach no verdict
are reported as `UNKNOWN — not checked` and counted separately, so an unanalysable
file never quietly looks like a pass.

### Or into GitHub code scanning

`--sarif` emits SARIF 2.1.0, which lands findings in the Security tab:

```yaml
      - run: |
          pip install git+https://github.com/nickharris808/ctbench@main
          ctbench check rtl/*.v --secret key --sarif > ctbench.sarif
        continue-on-error: true
      - uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: ctbench.sarif
```

`continue-on-error` matters: `ctbench check` exits non-zero when it finds something,
and you want the upload step to run anyway.

---

## 7. Score a different tool

The corpus is a benchmark, so you can grade anything against it — including a tool
that is not this one. Produce a JSON map of fixture name to verdict, then:

```console
$ ctbench validate my-submission.json
VALID     my-tool 0.3: covers all 18 scored fixtures
...
$ ctbench leaderboard
| # | Tool | Sound | Pairs | Correct | Imprecise | Abstained | Control |
|---|---|---|---|---|---|---|---|
| 1 | ctbench-reference 1.0.0 | yes | 8/8 | 18/18 | 0 | 0 | pass |
| 2 | naive-syntactic 0.1 | **NO** | 7/8 | 16/18 | 1 | 0 | **wolf** |
```

Ranking is lexicographic with soundness first: **a tool that calls one leaky design
safe ranks below every sound tool**, however accurate it is otherwise. Submissions
are validated before scoring, so answering only the easy half is not a route up the
board.

The `Control` column is `barrett_buggy.v` — a design that is genuinely constant-time
*and* functionally wrong. A timing tool that flags it is crying wolf, and the
leaderboard records that.

---

## Where to go next

- [SCOPE.md](SCOPE.md) — what a verdict does and does not entitle you to say.
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — the errors you will actually hit.
- [`ct-mask`](https://github.com/nickharris808/ct-mask) — if your countermeasure is
  masking rather than constant time.
- [`patchproof`](https://github.com/nickharris808/patchproof) — if the bug is a
  bounds check rather than a timing channel.
- [Live demo](https://huggingface.co/spaces/nickh007/hw-verify) — the same analyzer
  in your browser, nothing installed.
