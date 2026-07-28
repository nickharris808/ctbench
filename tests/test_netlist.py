"""The Yosys netlist frontend.

This frontend exists because the RTL parser must refuse hierarchical designs, and
almost all real RTL is hierarchical — so the honest answer was also the useless one.
After `flatten`, the constructs it refuses have been elaborated away.

The two load-bearing groups here:

* **the differential** — both frontends must reach the same verdict on every fixture
  the RTL path can read. They share `verdict_for`, so any divergence comes from
  parsing, and a divergence means one of them is wrong;
* **the refusals** — a netlist is a cell graph, and an unmodelled cell means missing
  edges. Missing edges make leaky designs look clean, so an unknown cell must refuse
  rather than be skipped. That is the same discipline as the RTL path, and it is more
  important here because the failure is silent.

Tests that need Yosys skip without it; the JSON-level tests run everywhere.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from ctbench.cone import CONSTANT_TIME, LEAKY, UNKNOWN, check, check_netlist
from ctbench.netlist import (
    NetlistError,
    UnknownCell,
    known_cell_types,
    parse_netlist,
)

HAVE_YOSYS = shutil.which("yosys") is not None
needs_yosys = pytest.mark.skipif(not HAVE_YOSYS, reason="yosys is not installed")


def synth(tmp_path, name: str, source: str) -> str:
    """Run Yosys the way the documentation tells the user to."""
    v = tmp_path / f"{name}.v"
    v.write_text(source)
    out = tmp_path / f"{name}.json"
    subprocess.run(
        ["yosys", "-q", "-p",
         (f"read_verilog {v}; hierarchy -top {name}; proc; flatten; opt_clean; "
          f"write_json {out}")],
        check=True, capture_output=True,
    )
    return str(out)


# A matched pair whose completion signal is driven from inside a child module, so the
# RTL frontend cannot read either one.
HIER_LEAKY = """
module cmp_child (clk, rst, a, b, hit);
    input clk, rst; input [7:0] a, b; output hit;
    reg r;
    assign hit = r & (a == b);
    always @(posedge clk) if (rst) r <= 1'b0; else r <= 1'b1;
endmodule
module hier_leaky (clk, rst, key, guess, done);
    input clk, rst; input [7:0] key, guess; output done;
    cmp_child u (.clk(clk), .rst(rst), .a(key), .b(guess), .hit(done));
endmodule
"""

HIER_CLEAN = """
module ctr_child (clk, rst, a, b, hit);
    input clk, rst; input [7:0] a, b; output hit;
    reg [3:0] cnt;
    assign hit = (cnt == 4'd8);
    always @(posedge clk) if (rst) cnt <= 4'd0; else cnt <= cnt + 1'b1;
endmodule
module hier_clean (clk, rst, key, guess, done);
    input clk, rst; input [7:0] key, guess; output done;
    ctr_child u (.clk(clk), .rst(rst), .a(key), .b(guess), .hit(done));
endmodule
"""


# ---------------------------------------------------------------------------
# The unlock.
# ---------------------------------------------------------------------------

@needs_yosys
def test_hierarchical_leak_is_found_where_the_rtl_frontend_must_refuse(tmp_path):
    """The whole reason this frontend exists."""
    src = HIER_LEAKY
    assert check(src, "done", ["key", "guess"], "hier_leaky").status == UNKNOWN, (
        "the RTL frontend should still refuse this — if it does not, this test is "
        "no longer testing the thing it was written for"
    )
    v = check_netlist(synth(tmp_path, "hier_leaky", src), "done", ["key", "guess"])
    assert v.status == LEAKY, v.reason
    assert set(v.reaching) == {"key", "guess"}


@needs_yosys
def test_hierarchical_clean_design_is_cleared(tmp_path):
    """The other half of the pair: refusing everything would also 'find' the leak."""
    v = check_netlist(synth(tmp_path, "hier_clean", HIER_CLEAN), "done", ["key", "guess"])
    assert v.status == CONSTANT_TIME, v.reason
    assert v.reaching == []


@needs_yosys
def test_the_netlist_frontend_separates_the_matched_pair(tmp_path):
    leaky = check_netlist(synth(tmp_path, "hier_leaky", HIER_LEAKY), "done", ["key", "guess"])
    clean = check_netlist(synth(tmp_path, "hier_clean", HIER_CLEAN), "done", ["key", "guess"])
    assert (leaky.status, clean.status) == (LEAKY, CONSTANT_TIME)


# ---------------------------------------------------------------------------
# The differential: two frontends, one answer.
# ---------------------------------------------------------------------------

@needs_yosys
def test_both_frontends_agree_on_every_scored_fixture(tmp_path, scored_manifest, fixture_dir):
    """A divergence means one of the two is wrong, and we would not know which."""
    disagree = []
    for e in scored_manifest:
        src = (fixture_dir / e["file"]).read_text()
        rtl = check(src, e["observation"], e["secrets"], e.get("module"))
        if rtl.status == UNKNOWN:
            continue                      # nothing to compare against
        top = e.get("module") or e["file"].removesuffix(".v")
        try:
            j = synth(tmp_path, top, src)
        except subprocess.CalledProcessError:
            continue                      # synthesis failure is not a frontend bug
        nl = check_netlist(j, e["observation"], e["secrets"])
        if nl.status != rtl.status:
            disagree.append(f"{e['file']}: RTL={rtl.status} netlist={nl.status} ({nl.reason})")
    assert not disagree, "frontends disagree:\n  " + "\n  ".join(disagree)


# ---------------------------------------------------------------------------
# Refusals. An unmodelled cell is missing edges, and missing edges hide leaks.
# ---------------------------------------------------------------------------

def _netlist(cells: dict, ports: dict | None = None, name: str = "top") -> dict:
    return {"modules": {name: {
        "ports": ports or {
            "key": {"direction": "input", "bits": [2]},
            "done": {"direction": "output", "bits": [3]},
        },
        "cells": cells,
        "netnames": {"key": {"bits": [2]}, "done": {"bits": [3]}},
    }}}


def test_an_unknown_cell_type_refuses_rather_than_being_skipped():
    d = _netlist({"u1": {"type": "$totally_made_up",
                         "port_directions": {"A": "input", "Y": "output"},
                         "connections": {"A": [2], "Y": [3]}}})
    with pytest.raises(UnknownCell) as e:
        parse_netlist(d, "top")
    msg = str(e.value)
    assert "unmodelled" in msg
    assert "no verdict is returned" in msg
    assert "leaky design into a clean verdict" in msg


def test_a_blackbox_technology_cell_refuses_and_says_so():
    """A cell with no '$' prefix survived flattening; the hint should say that."""
    d = _netlist({"u1": {"type": "sky130_fd_sc_hd__and2_1",
                         "port_directions": {"A": "input", "X": "output"},
                         "connections": {"A": [2], "X": [3]}}})
    with pytest.raises(UnknownCell, match="blackbox"):
        parse_netlist(d, "top")


def test_check_netlist_reports_an_unknown_cell_as_unknown_not_clean():
    """Through the non-raising path, the refusal must not become CONSTANT_TIME."""
    import tempfile
    from pathlib import Path

    d = _netlist({"u1": {"type": "$nope",
                         "port_directions": {"A": "input", "Y": "output"},
                         "connections": {"A": [2], "Y": [3]}}})
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "n.json"
        p.write_text(json.dumps(d))
        v = check_netlist(str(p), "done", ["key"], "top")
    assert v.status == UNKNOWN
    assert v.constant_time is False


def test_scopeinfo_is_ignored_only_while_it_carries_no_signal():
    """Metadata cells are the one exception, and it is checked rather than assumed."""
    inert = {"u": {"type": "$scopeinfo", "connections": {}, "port_directions": {}},
             "g": {"type": "$and", "port_directions": {"A": "input", "Y": "output"},
                   "connections": {"A": [2], "Y": [3]}}}
    mod = parse_netlist(_netlist(inert), "top")
    assert "done" in mod.deps          # parsed fine, scopeinfo skipped

    # the same type, but wired: no longer inert, so it must refuse
    wired = dict(inert)
    wired["u"] = {"type": "$scopeinfo",
                  "port_directions": {"A": "input", "Y": "output"},
                  "connections": {"A": [2], "Y": [3]}}
    with pytest.raises(UnknownCell):
        parse_netlist(_netlist(wired), "top")


@pytest.mark.parametrize("bad,match", [
    ({}, "no modules"),
    ({"modules": {}}, "no modules"),
    ({"modules": {"a": {"cells": {}}, "b": {"cells": {}}}}, "Pass --top"),
])
def test_malformed_netlists_refuse_with_a_reason(bad, match):
    with pytest.raises(NetlistError, match=match):
        parse_netlist(bad)


def test_naming_a_module_that_is_not_there_lists_what_is():
    d = {"modules": {"alpha": {"cells": {}}, "beta": {"cells": {}}}}
    with pytest.raises(NetlistError) as e:
        parse_netlist(d, "gamma")
    assert "alpha" in str(e.value) and "beta" in str(e.value)


def test_a_module_with_no_cells_refuses():
    """An empty graph would report CONSTANT_TIME having checked nothing."""
    with pytest.raises(NetlistError, match="no cells"):
        parse_netlist(_netlist({}), "top")


def test_load_netlist_rejects_non_json_and_missing_files(tmp_path):
    from ctbench.netlist import load_netlist

    p = tmp_path / "x.json"
    p.write_text("this is not json")
    with pytest.raises(NetlistError, match="not valid JSON"):
        load_netlist(p)
    with pytest.raises(NetlistError, match="cannot read"):
        load_netlist(tmp_path / "nope.json")


def test_known_cell_types_covers_both_bit_and_word_level():
    k = known_cell_types()
    for cell in ("$_AND_", "$_DFF_P_", "$and", "$dff", "$mux", "$eq"):
        assert cell in k, cell
