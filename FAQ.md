# FAQ

Written from objections people actually raise, including the uncomfortable ones.

---

### Is this a formal proof?

Partly, and the parts differ.

- **ctbench** is a *syntactic* over-approximation. It proves something real — no
  declared secret appears in the observation's fan-in cone — but it reasons about
  dependency structure, not semantics. It is a sound baseline, not a model checker.
- **ct-mask** discharges each probe as a machine-checked refutation with z3. That is a
  proof, about a stated model (glitch-free, first order, 2-share).
- **patchproof** proves infeasibility twice over — bit-precise, and as a Farkas
  certificate — and the certificate is independently replayable. That is the most
  formal thing here.

None of them proves your *system* is secure. They prove specific properties of
specific models, and each `SCOPE.md` says which.

### Why does it keep saying UNKNOWN on my design?

Because it is refusing to guess. The RTL parser reads one flat module of `assign`
statements and `always` blocks; a submodule instantiation, a `for` loop, `generate`,
a `function`, or a macro creates dependency edges it cannot follow.

Skipping them would not make the answer vaguer — it would delete edges, and a signal
with no edges has an empty cone, and an empty cone contains no secrets, and no secrets
reads as *safe*. So you would get a confident wrong answer instead of an honest
non-answer.

Use the netlist frontend, which is what it is for:

```bash
yosys -q -p 'read_verilog rtl/*.v; hierarchy -top top; proc; flatten; opt_clean; write_json build/top.json'
ctbench check --netlist build/top.json --secret key
```

### Why won't it just infer which inputs are secret?

Because it would be wrong often enough to be dangerous, and the failure is invisible.
A tool that guesses `key` is secret and `iv` is not produces a confident verdict about
the wrong property, and nothing in the output tells you it guessed. Declaring secrets
takes ten seconds and makes the claim checkable.

### It flagged something I am sure is fine.

Quite possibly. The analysis follows every dependency edge whether or not the path can
be taken at run time, so a path through a branch that never executes is still a path.

Run `ctbench explain` — that is exactly why it exists. Read the chain; if it is dead,
the verdict is *imprecise*, which costs you time. The opposite error, calling a leaky
design safe, ships a vulnerability. The tool prefers the first, and the leaderboard
scores it that way: imprecision loses points, unsoundness fails the run outright.

If you have a design where a `LEAKY` verdict is clearly wrong, that is a valuable
fixture — please open an issue.

### It said CONSTANT_TIME and my design still leaks.

Check, in order: were the right secrets declared? Is the channel actually timing (this
says nothing about power or EM)? Is the leak introduced after synthesis? Is the
observation signal the one the attacker sees?

If none of those explain it, that is a soundness bug and the most valuable thing you
can report. A fixture we get wrong is exactly what the corpus is missing.

### How is this different from a constant-time checker for software?

Software tools (ctgrind, dudect, ct-verif and the like) analyse instruction streams or
measure execution. These analyse *hardware description* — the property is whether a
completion signal's value depends on secret data, which is a question about circuit
structure rather than instruction timing.

### Why should I trust the certificate?

You should not have to, which is the point. `patchproof-verify` is a separate Rust
implementation, sharing no code with the prover, and both run the same 30 test vectors
— a disagreement fails both builds. Replaying a certificate is multiply, add, check
the variables cancel, check the constant is positive. It is small enough to audit in
an afternoon, and you are encouraged to.

### Is `UNKNOWN` just a way of dodging hard cases?

It is a way of not lying about them. Concretely, `UNKNOWN` exits `2`, `constant_time`
is `False` for it, the GitHub Action counts it separately from `checked` and never
renders it as constant-time, SARIF reports it at warning level rather than omitting it,
and a baseline can acknowledge one without ever converting it to a pass.

If it were a dodge, it would be silent. It is the loudest verdict in the tool.

### The benchmark only has 18 scored fixtures. Is that enough?

For a methodology demonstration, yes; for a definitive ranking, no, and the leaderboard
says so. What the corpus buys is not size but *structure*: eight matched pairs, where
each safe design has a leaky twin with an identical interface, so calling everything
leaky scores zero. Plus an out-of-remit control that is genuinely constant-time and
functionally wrong — a tool that flags it is crying wolf.

Growing it is the most valuable contribution available. See [CONTRIBUTING.md](CONTRIBUTING.md).

### Why is nothing on PyPI?

No credentials are configured for this project yet. Everything installs from GitHub
today, which works identically:

```bash
pip install git+https://github.com/nickharris808/hw-verify@main
```

The release workflows are already wired for PyPI Trusted Publishing (OIDC, no stored
token) and need only the account-side configuration.

### Can I use this commercially?

Yes. Apache-2.0 throughout; the RTL corpus is CC-BY-4.0 and four picorv32-derived
fixtures remain ISC. No copyleft, no legal conversation needed.

### What is the commercial boundary you keep mentioning?

Everything open analyses a design you hand it **in full**. Proving a property to an
integrator, auditor, or customer who *never receives* your netlist — a verdict bound
to a commitment of a design that stays hidden — is a different problem and a
commercial one. Nothing in these packages implements a commitment scheme, an
attestation, or a confidential verification path, and saying otherwise would be the
same kind of overclaim the tools are built to avoid.

### Who maintains this, and can I contribute?

See [CONTRIBUTING.md](CONTRIBUTING.md). The single most useful contribution is a
fixture we get *wrong* — especially one where we report `CONSTANT_TIME` and you can
show a leak.
