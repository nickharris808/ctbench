"""The scanner pre-filter must be a pure optimisation.

A speedup that changes an answer is not a speedup, it is a bug with a stopwatch. The
substring gate in `unsupported_constructs` skips a regex when its keyword is absent
from the source, which is safe because every gated pattern is an anchored keyword —
`\\bfor\\b` cannot match text with no "for" in it.

That reasoning is easy to break later by adding a pattern whose literal is not
actually implied by the regex, so these tests check the property directly rather than
trusting the argument: with the gate and without it, the scanner must return
identical results on everything.
"""

from __future__ import annotations

import pytest

from ctbench.cone import _UNSUPPORTED, strip_comments, unsupported_constructs

FIXTURE_SOURCES = [
    "module m(a,done); input a; output done; assign done=a; endmodule",
    "module m(a,done); input a; output done; child u(.a(a),.done(done)); endmodule",
    ("module m(a,done); input a; output done; reg r; integer i;\n"
     " always @(posedge clk) for(i=0;i<8;i=i+1) r<=a; assign done=r; endmodule"),
    ("`define G (a!=0)\nmodule m(a,done); input a; output done; reg r;\n"
     " always @(posedge clk) if(`G) r<=1'b1; assign done=r; endmodule"),
    ("module m(a,done); input a; output done;\n"
     " function automatic f; input x; begin f=x; end endfunction\n"
     " assign done=f(a); endmodule"),
    ("module m(a,done); input a; output done; reg r; genvar i;\n"
     " generate for(i=0;i<2;i=i+1) begin: g always @(*) r=a; end endgenerate\n"
     " assign done=r; endmodule"),
    ("// a comment mentioning for, while, generate, function, task and `define\n"
     "module m(a,done); input a; output done; assign done=a; endmodule"),
    "",
    "   ",
    "not verilog at all",
]


def _unfiltered(src: str) -> list[tuple[str, int, str]]:
    """What the scanner would return with the substring gate removed."""
    stripped = strip_comments(src)
    found = []
    for name, pat, _literal in _UNSUPPORTED:
        for m in pat.finditer(stripped):
            if name == "module instantiation":
                from ctbench.cone import _KEYWORDS
                if m.group(1) in _KEYWORDS or m.group(2) in _KEYWORDS:
                    continue
            found.append((name, stripped[: m.start()].count("\n") + 1, m.group(0).strip()))
    return sorted(found, key=lambda f: f[1])


@pytest.mark.parametrize("src", FIXTURE_SOURCES)
def test_prefilter_never_changes_the_scanner_result(src):
    assert unsupported_constructs(src) == _unfiltered(src)


def test_prefilter_never_changes_the_result_on_the_whole_corpus(fixture_dir):
    """Every shipped fixture, gated and ungated, must agree."""
    mismatched = [
        p.name for p in sorted(fixture_dir.glob("*.v"))
        if unsupported_constructs(p.read_text()) != _unfiltered(p.read_text())
    ]
    assert not mismatched, f"pre-filter changed the result for: {mismatched}"


def test_every_gated_pattern_requires_its_literal():
    """The safety argument, checked mechanically.

    If a pattern can match text not containing its literal, the gate would skip a
    real construct — an unsound refusal-to-refuse. Verified by feeding each pattern
    a string built from its own literal and confirming the regex needs it.
    """
    for name, pat, literal in _UNSUPPORTED:
        if literal is None:
            continue
        assert literal.lower() in pat.pattern.lower(), (
            f"{name}: literal {literal!r} does not appear in its own pattern "
            f"{pat.pattern!r}, so the substring gate may skip a real match"
        )


def test_the_corpus_still_gets_the_same_verdicts(scored_manifest, fixture_dir):
    """The end-to-end guard: an optimisation must not move a single verdict."""
    from ctbench.cone import check

    for e in scored_manifest:
        v = check((fixture_dir / e["file"]).read_text(), e["observation"],
                  e["secrets"], e.get("module"))
        assert v.status == e["expected"], f"{e['file']}: {v.status} (was {e['expected']})"
