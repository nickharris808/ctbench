"""Regression tests for the unsoundness class: a confident answer that is wrong.

Every test here failed before the refusal machinery existed, and each one failed in
the worst possible direction -- the analyzer reported CONSTANT_TIME for a design that
genuinely leaks.  The cause was always the same shape: `parse` reads `assign`
statements, net declarations with initialisers, and `always` blocks, and silently
ignores everything else.  Ignoring a construct does not lose a little precision; it
deletes dependency edges, and a signal with no edges has an empty cone, and an empty
cone contains no secrets, and no secrets reads as safe.

The governing rule these tests pin down is: when the analysis cannot see the design,
it must refuse, never guess.  The oracle for the whole file is one line -- no input
may produce a confident-looking answer that is wrong -- so what is asserted is almost
never a particular message, only that the verdict is not a false CONSTANT_TIME.
"""

from __future__ import annotations

import pytest

from ctbench.cone import (
    CONSTANT_TIME,
    LEAKY,
    UNKNOWN,
    AnalysisRefused,
    UndrivenObservation,
    UnknownObservation,
    UnsupportedConstruct,
    analyse,
    check,
    unsupported_constructs,
)

# Each source leaks x (and sometimes y) into `done` through a construct the cone
# analysis cannot follow.  Truth for every one of them is "not constant-time".
LEAKY_THROUGH_UNREADABLE_CONSTRUCT = {
    "submodule instantiation": """
        module top(clk, x, y, done);
          input clk; input [7:0] x, y; output done;
          leaky_child u_child (.clk(clk), .x(x), .y(y), .done(done));
        endmodule
    """,
    "for loop in always": """
        module top(clk, x, done);
          input clk; input [7:0] x; output done; reg r; integer i;
          always @(posedge clk) begin
            for (i = 0; i < 8; i = i + 1) if (x[i]) r <= 1'b1;
          end
          assign done = r;
        endmodule
    """,
    "generate block": """
        module top(clk, x, done);
          input clk; input [7:0] x; output done; reg r;
          genvar i;
          generate for (i = 0; i < 8; i = i + 1) begin: g
            always @(posedge clk) if (x[i]) r <= 1'b1;
          end endgenerate
          assign done = r;
        endmodule
    """,
    "function definition": """
        module top(clk, x, done);
          input clk; input [7:0] x; output done;
          function automatic leaky; input [7:0] a; begin leaky = (a == 8'hAA); end endfunction
          assign done = leaky(x);
        endmodule
    """,
    "macro hiding a guard": """
        `define GUARD (x != 0)
        module top(clk, x, done);
          input clk; input [7:0] x; output done; reg r;
          always @(posedge clk) if (`GUARD) r <= 1'b1;
          assign done = r;
        endmodule
    """,
    "while loop": """
        module top(clk, x, done);
          input clk; input [7:0] x; output done; reg r; integer i;
          always @(posedge clk) begin
            i = 0;
            while (i < x) begin r <= 1'b1; i = i + 1; end
          end
          assign done = r;
        endmodule
    """,
}


@pytest.mark.parametrize("name", sorted(LEAKY_THROUGH_UNREADABLE_CONSTRUCT))
def test_unreadable_construct_never_yields_a_false_constant_time(name):
    """The core anti-hallucination property, one case per construct.

    Each of these returned CONSTANT_TIME with an empty cone before the fix.
    """
    src = LEAKY_THROUGH_UNREADABLE_CONSTRUCT[name]
    v = check(src, "done", ["x", "y"], "top")
    assert v.status != CONSTANT_TIME, (
        f"{name}: reported CONSTANT_TIME for a design whose dependencies it "
        f"could not read — this is the unsound direction"
    )
    assert v.status == UNKNOWN
    assert not v.constant_time, "UNKNOWN must never be truthy for constant_time"


@pytest.mark.parametrize("name", sorted(LEAKY_THROUGH_UNREADABLE_CONSTRUCT))
def test_the_refusal_says_what_was_unreadable_and_what_to_do(name):
    """A refusal a user cannot act on just moves the problem."""
    src = LEAKY_THROUGH_UNREADABLE_CONSTRUCT[name]
    with pytest.raises(UnsupportedConstruct) as e:
        analyse(src, "done", ["x", "y"], "top")
    msg = str(e.value)
    assert e.value.line > 0, "refusal must locate the construct"
    assert e.value.construct in msg
    assert "no verdict" in msg
    # and it must suggest a way forward
    assert "--module" in msg or "Flatten" in msg


def test_a_constant_driver_is_analysed_not_refused():
    """`assign done = 1'b1;` has an empty cone but was genuinely read.

    Refusing here would make the tool useless on the very designs it should pass:
    the refusal condition is "no driver was read", not "the cone came out empty".
    """
    src = "module top(clk, x, done); input clk; input [7:0] x; output done; assign done = 1'b1; endmodule"
    assert analyse(src, "done", ["x"], "top").status == CONSTANT_TIME


def test_output_declared_but_never_driven_refuses():
    """An unread driver is not evidence of safety."""
    src = "module top(clk, x, done); input clk; input [7:0] x; output done; endmodule"
    with pytest.raises(UndrivenObservation) as e:
        analyse(src, "done", ["x"], "top")
    assert "empty" in str(e.value)
    assert check(src, "done", ["x"], "top").status == UNKNOWN


def test_unknown_carries_its_reason():
    """An UNKNOWN with no reason is indistinguishable from a crash."""
    v = check(LEAKY_THROUGH_UNREADABLE_CONSTRUCT["for loop in always"], "done", ["x"], "top")
    assert v.status == UNKNOWN
    assert v.reason and len(v.reason) > 40
    assert v.to_dict()["reason"] == v.reason
    assert v.to_dict()["verdict"] == UNKNOWN


def test_misspelled_observation_names_the_real_outputs():
    """The most common user error deserves the most useful message."""
    src = "module top(clk, x, done); input clk; input [7:0] x; output done; assign done = 1'b1; endmodule"
    with pytest.raises(UnknownObservation, match="Declared outputs"):
        analyse(src, "dnoe", ["x"], "top")


# ---------------------------------------------------------------------------
# The scanner must not become so eager that it refuses the corpus.
# A tool that refuses everything is sound and worthless.
# ---------------------------------------------------------------------------

def test_scanner_ignores_constructs_named_in_comments():
    """Prose about a `for` loop is not a `for` loop.

    The corpus is heavily commented and several comments use Markdown backticks and
    the words 'function' and 'while', so scanning unstripped source refuses almost
    the whole benchmark.
    """
    src = """
        // This module uses no for loop and no generate block; the `done` signal
        // is a function of a counter, computed while running. See `ct_gcd`.
        /* function, task, generate, `define — all only mentioned here. */
        module top(clk, x, done);
          input clk; input [7:0] x; output done; reg r;
          always @(posedge clk) r <= 1'b1;
          assign done = r;
        endmodule
    """
    assert unsupported_constructs(src) == []
    assert analyse(src, "done", ["x"], "top").status == CONSTANT_TIME


def test_keyword_shapes_are_not_read_as_instantiations():
    """`always @(...)`, `if (...)` and `case (...)` match IDENT IDENT '(' too."""
    src = """
        module top(clk, x, done);
          input clk; input [7:0] x; output done; reg r;
          always @(posedge clk)
            if (x[0]) r <= 1'b1;
            else case (x[1]) 1'b0: r <= 1'b0; default: r <= 1'b1; endcase
          assign done = r;
        endmodule
    """
    assert unsupported_constructs(src) == []
    assert analyse(src, "done", ["x"], "top").status == LEAKY


def test_the_whole_scored_corpus_still_gets_a_verdict(scored_manifest, fixture_dir):
    """The refusal must not have cost the benchmark its answers."""
    for entry in scored_manifest:
        src = (fixture_dir / entry["file"]).read_text()
        v = check(src, entry["observation"], entry["secrets"])
        assert v.status == entry["expected"], f"{entry['file']}: {v.status} (reason: {v.reason})"


# ---------------------------------------------------------------------------
# Malformed, empty, enormous, out-of-distribution.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src", [
    "",
    "   \n\t  \n",
    "not verilog at all, just prose",
    "module top(",
    "module top(clk); input clk;",                      # no endmodule
    "/* unterminated comment\nmodule top(a); endmodule",
    "\x00\x01\x02binary garbage\xff",
])
def test_malformed_input_raises_and_never_returns_a_verdict(src):
    """Junk in must not produce a verdict out."""
    with pytest.raises((ValueError, AnalysisRefused)):
        analyse(src, "done", ["x"])


def test_crlf_and_unicode_identifiers_do_not_crash():
    src = "module top(clk, x, done);\r\n input clk;\r\n input [7:0] x;\r\n output done;\r\n reg r;\r\n always @(posedge clk) if (x) r <= 1'b1;\r\n assign done = r;\r\nendmodule\r\n"
    assert check(src, "done", ["x"], "top").status == LEAKY
    # a non-ASCII identifier is simply not an identifier here; it must not crash
    check("module tøp(a); input a; endmodule", "a", ["a"])


def test_enormous_input_terminates_without_recursion_error():
    """A 4000-signal chain: the cone walk must be iterative, not recursive."""
    n = 4000
    body = "\n".join(f"  assign s{i} = s{i - 1};" for i in range(1, n))
    src = (
        f"module big(x, done);\n input x;\n output done;\n"
        f"  assign s0 = x;\n{body}\n  assign done = s{n - 1};\nendmodule"
    )
    v = analyse(src, "done", ["x"], "big")
    assert v.status == LEAKY, "a secret at the head of a long chain must still reach"
    assert v.cone_size >= n


def test_multi_module_file_analyses_the_named_module_not_the_first():
    src = """
        module first(a, done); input a; output done; assign done = 1'b1; endmodule
        module second(k, done); input k; output done; assign done = k; endmodule
    """
    assert analyse(src, "done", ["k"], "second").status == LEAKY
    assert analyse(src, "done", ["k"], "first").status == CONSTANT_TIME
    with pytest.raises(ValueError, match="not found"):
        analyse(src, "done", ["k"], "third")
