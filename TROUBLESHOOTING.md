# Troubleshooting

Every error message the tool can produce, what it means, and what to do. All of the
messages below are copied from actual runs.

---

## `UNKNOWN — no verdict was reached` (exit 2)

```
line 5: module instantiation is outside the supported Verilog subset
('child u_child ('). Dependencies created by it would be invisible to the cone
analysis, so no verdict is returned. Flatten the design to a single module of
assign/always statements, or analyse the submodule directly with --module.
```

**This is the tool working.** It is not an internal error and it is not a failure to
be worked around — it is the analysis declining to answer about a design it cannot
read. Reporting `CONSTANT_TIME` here would be asserting safety about logic it never
looked at.

**Fix**, in order of preference:

1. Analyse the submodule that actually drives the completion signal:
   `ctbench check rtl/child.v --observation done --secret key`
2. Point at a flattened netlist if your synthesis flow emits one:
   `yosys -p "read_verilog rtl/*.v; flatten; write_verilog build/flat.v"`
3. Extract the completion path into its own module. This is usually a good idea
   anyway — a completion signal spread across a hierarchy is hard to reason about
   by hand too.

The full list of constructs that trigger this is in [SCOPE.md](SCOPE.md).

**Do not** work around it by deleting the construct from a copy of the file and
checking that. You will get a verdict about a design you are not shipping.

---

## `observation 'done' is declared in 'top' but nothing in the parsed source drives it`

The signal is in the port list, but no `assign` or `always` block the parser read
ever writes to it. Its fan-in cone is just itself, which contains no secrets, which
would report as constant-time — so the tool refuses.

**Usually one of:**

- the driver is in a submodule (see above);
- the driver uses a construct outside the subset;
- you named an input rather than the completion output.

---

## `observation 'dnoe' is not declared or driven in 'cmp_leaky'. Declared outputs: done, equal.`

A typo. The message lists the module's actual outputs — pick one of those, or pass
`--module` if you meant a different module in a multi-module file.

---

## `ctbench: no secrets given for aes_core.v`

```
Secrets are a specification choice and are never inferred — guessing which inputs
are sensitive would produce confident verdicts about the wrong property.
Pass --secret NAME (repeatable), or name a bundled fixture whose secrets the
manifest already records (ctbench fixtures).
```

There is no default and there will not be one. `--secret` is repeatable:

```bash
ctbench check rtl/aes_core.v --observation done --secret key --secret nonce
```

For a bundled fixture the manifest already records them, so `ctbench check
cmp_leaky.v` works with no flags.

---

## `ctbench: no such file 'cmp_leaky.v', and no bundled fixture of that name`

Either the path is wrong, or you meant a fixture whose name you have misspelled. Run
`ctbench fixtures` to list all 27 with their expected verdicts.

Bundled fixtures resolve by bare name from any directory, because they live inside
the installed package — you do not need to clone the repository to use them.

---

## `module 'foo' not found. This file defines: cmp_leaky.`

The file parsed, but contains no module of that name. The message lists the modules
it *does* define — pick one, or drop `--module` to analyse the first.

Reported as `UNKNOWN` (exit 2), not a crash: naming the wrong module means nothing
was analysed, and that must never be mistaken for a clean result.

## `no module found: the source contains no 'module ... endmodule' block`

The file is empty, truncated, or is not Verilog. Also reported as `UNKNOWN`.

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | every checked file is `CONSTANT_TIME` |
| `1` | at least one `LEAKY`, and no `UNKNOWN` |
| `2` | at least one `UNKNOWN` — **no verdict**, do not read as a pass |

Exit 2 deliberately outranks exit 1: a CI job guarding only against `1` must not be
satisfied by "we could not tell".

In a shell, remember that `$?` after a pipeline reports the *last* command's status:

```bash
ctbench check rtl/top.v --secret key | tee out.json ; echo $?   # tee's status, not ctbench's
ctbench check rtl/top.v --secret key > out.json ; echo $?       # correct
```

---

## "It said LEAKY but I am sure that path is never taken"

Quite possibly true. The analysis is a syntactic over-approximation: it follows every
edge in the dependency graph whether or not the path is reachable at run time. That
is why a `LEAKY` verdict names the reaching signals — it is an invitation to check,
not a conviction.

If the path really is dead, the verdict is *imprecise*, which costs you engineering
time. The opposite error — calling a leaky design safe — ships a vulnerability, so
the tool is built to prefer the first. The leaderboard scores it the same way:
imprecision loses points, unsoundness fails the run outright.

---

## "It said CONSTANT_TIME but my design still leaks"

Check, in this order:

1. **Did you declare the right secrets?** A verdict is only about the inputs you
   named.
2. **Is the channel actually timing?** This analysis says nothing about power, EM,
   cache, or microarchitectural leakage. A constant-time design can leak badly
   through power.
3. **Is the leak after synthesis?** The analysis reads RTL; a synthesis tool can
   introduce a data-dependent optimisation the RTL did not have.
4. **Is the observation signal the right one?** Completion timing is one observable.
   If an attacker can see a different signal, check that one too.

If none of those explain it, that is a genuine unsoundness bug and the most valuable
thing you can report. Please open an issue with the module — a fixture that we get
wrong is exactly what the corpus is missing.

---

## CI and integration

**SARIF upload fails or shows nothing.** `ctbench check --sarif` exits non-zero when
it finds a leak, which stops the upload step. Add `continue-on-error: true` to the
step that runs ctbench, not to the upload.

**SARIF paths do not resolve on GitHub.** URIs are emitted relative to the working
directory. Run ctbench from the repository root, or the paths will not match what
GitHub expects.

**The Action can't find ctbench.** ctbench is not on PyPI; `pip install ctbench`
404s. Install from the repository:
`pip install git+https://github.com/nickharris808/ctbench@main`.

---

## Still stuck?

- [SCOPE.md](SCOPE.md) — what a verdict does and does not mean.
- [TUTORIAL.md](TUTORIAL.md) — the whole workflow end to end.
- [Live demo](https://huggingface.co/spaces/nickh007/hw-verify) — paste your module
  in a browser and see what happens, nothing installed.
