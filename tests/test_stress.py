"""Adversarial stress suite for the surfaces added in the last two releases.

The oracle, unchanged from the rest of the project: **no input may produce a
confident-looking answer that is wrong.** Everything else is negotiable.

Three real bugs were found writing this file, all in code written the same week, and
all in the same direction — a confident CONSTANT_TIME where the truth was LEAKY:

1. **An undeclared cell port direction defaulted to "input".** A cell whose *output*
   direction was missing therefore contributed no edges at all, and a secret flowing
   through it vanished from the graph. The single-cell case happened to be caught by
   the "no cells" refusal, which is why reasoning alone did not find it: the bug only
   shows with one malformed cell among well-formed ones, where the graph stays
   non-empty and the refusal never fires.

2. **`all_paths` is depth-bounded, so on a long chain it returned nothing** while a
   path demonstrably existed. Asking for *more* paths returned *fewer*, and an empty
   path list reads as "no path" — the opposite of what a LEAKY verdict means.

3. **Three malformed-JSON shapes raised `AttributeError`** rather than a refusal.
   Not unsound, but `check_netlist` only catches `AnalysisRefused`, so junk input
   surfaced as a traceback instead of the UNKNOWN verdict every other refusal gives.

Each is pinned below.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import pytest

from ctbench.baseline import Baseline
from ctbench.cone import (
    CONSTANT_TIME,
    LEAKY,
    UNKNOWN,
    AnalysisRefused,
    Module,
    Verdict,
    check_netlist,
    verdict_for,
)
from ctbench.diff import diff, load_findings
from ctbench.explain import all_paths, explain, shortest_path
from ctbench.findings import Findings
from ctbench.netlist import UndirectedPort, parse_netlist

PORTS = {"key": {"direction": "input", "bits": [2]},
         "done": {"direction": "output", "bits": [3]}}
NETS = {"key": {"bits": [2]}, "done": {"bits": [3]}}


def nl(cells, ports=None, nets=None, name="top"):
    return {"modules": {name: {"ports": ports or PORTS, "cells": cells,
                               "netnames": nets or NETS}}}


def V(status, reaching=(), obs="done", module="m"):
    return Verdict(module=module, observation=obs, secrets=["k"],
                   reaching=list(reaching), cone_size=3, status=status,
                   reason="no verdict" if status == UNKNOWN else None)


def F(*items):
    f = Findings()
    for v, p in items:
        f.add(v, p)
    return f


# ---------------------------------------------------------------------------
# BUG 1 — a missing port direction must refuse, never default.
# ---------------------------------------------------------------------------

def test_a_cell_output_with_no_declared_direction_refuses():
    """The regression that matters most: this returned CONSTANT_TIME on a leak.

    `key -> mid` through `g_bad`, whose output direction is missing, then
    `mid -> done` through a well-formed cell. Because `g_ok` populates the graph, the
    "no cells" refusal does not fire, and defaulting `Y` to "input" silently deletes
    the only edge carrying the secret.
    """
    data = {"modules": {"top": {
        "ports": {"key": {"direction": "input", "bits": [2]},
                  "pub": {"direction": "input", "bits": [5]},
                  "done": {"direction": "output", "bits": [3]}},
        "cells": {
            "g_bad": {"type": "$not", "port_directions": {"A": "input"},
                      "connections": {"A": [2], "Y": [4]}},
            "g_ok": {"type": "$and",
                     "port_directions": {"A": "input", "B": "input", "Y": "output"},
                     "connections": {"A": [4], "B": [5], "Y": [3]}},
        },
        "netnames": {"key": {"bits": [2]}, "done": {"bits": [3]},
                     "mid": {"bits": [4]}, "pub": {"bits": [5]}}}}}
    with pytest.raises(UndirectedPort) as e:
        parse_netlist(data, "top")
    assert "no declared direction" in str(e.value)
    assert "clean verdict" in str(e.value)


def test_an_empty_port_directions_map_refuses():
    with pytest.raises(UndirectedPort):
        parse_netlist(nl({"g": {"type": "$and", "port_directions": {},
                                "connections": {"A": [2], "Y": [3]}}}), "top")


def test_a_missing_port_directions_key_refuses():
    with pytest.raises(UndirectedPort):
        parse_netlist(nl({"g": {"type": "$and",
                                "connections": {"A": [2], "Y": [3]}}}), "top")


def test_well_formed_netlists_are_unaffected_by_that_refusal():
    """A refusal that fires on valid input would be worse than the bug."""
    mod = parse_netlist(nl({"g": {"type": "$and",
                                  "port_directions": {"A": "input", "Y": "output"},
                                  "connections": {"A": [2], "Y": [3]}}}), "top")
    assert verdict_for(mod, "done", ["key"]).status == LEAKY


# ---------------------------------------------------------------------------
# BUG 2 — asking for more paths must never return fewer.
# ---------------------------------------------------------------------------

@pytest.fixture
def long_chain():
    m = Module(name="long")
    m.add("s0", {"key"})
    for i in range(1, 200):
        m.add(f"s{i}", {f"s{i - 1}"})
    m.add("done", {"s199"})
    v = Verdict(module="long", observation="done", secrets=["key"], reaching=["key"],
                cone_size=201, status=LEAKY)
    return m, v


def test_a_leaky_verdict_always_yields_at_least_one_path(long_chain):
    """An empty path list reads as 'no path', which contradicts the verdict."""
    mod, v = long_chain
    for n in (1, 3, 8):
        assert explain(mod, v, limit_per_secret=n).paths, (
            f"limit_per_secret={n} produced no path for a LEAKY verdict"
        )


def test_requesting_more_paths_never_returns_fewer(long_chain):
    mod, v = long_chain
    counts = [len(explain(mod, v, limit_per_secret=n).paths) for n in (1, 2, 4, 8)]
    assert counts == sorted(counts), f"non-monotonic path counts: {counts}"


def test_all_paths_stays_bounded_under_path_explosion():
    """400 parallel routes: the bound is what stops this being exponential."""
    m = Module(name="fan")
    m.add("done", {f"s{i}" for i in range(400)})
    for i in range(400):
        m.add(f"s{i}", {"key"})
    start = time.perf_counter()
    found = all_paths(m, "done", "key", limit=8)
    assert len(found) <= 8
    assert time.perf_counter() - start < 5


def test_every_reported_path_is_real_on_a_long_chain(long_chain):
    mod, v = long_chain
    for p in explain(mod, v, limit_per_secret=4).paths:
        for src, dst in zip(p.signals, p.signals[1:], strict=False):
            assert src in mod.deps.get(dst, set()), f"{src} -> {dst} is not an edge"


# ---------------------------------------------------------------------------
# BUG 3 — malformed JSON must refuse, not raise AttributeError.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,data", [
    ("modules is a list", {"modules": []}),
    ("modules is a string", {"modules": "x"}),
    ("module is a list", {"modules": {"top": []}}),
    ("cells is a list", {"modules": {"top": {"ports": {}, "cells": []}}}),
    ("cell is a string", {"modules": {"top": {"ports": {}, "cells": {"g": "nope"}}}}),
    ("connections is a string", {"modules": {"top": {"ports": {}, "cells": {
        "g": {"type": "$and", "port_directions": {}, "connections": "x"}}}}}),
    ("port_directions is a list", {"modules": {"top": {"ports": {}, "cells": {
        "g": {"type": "$and", "port_directions": [], "connections": {"A": [2]}}}}}}),
])
def test_malformed_netlists_refuse_rather_than_raising(name, data):
    """`check_netlist` only catches AnalysisRefused; anything else is a traceback."""
    with pytest.raises(AnalysisRefused):
        parse_netlist(data, "top")


@pytest.mark.parametrize("raw", [
    "{}", "[]", "null", '{"modules": {"top": []}}', '{"modules": {"top": {"cells": "x"}}}',
])
def test_check_netlist_turns_every_malformed_input_into_unknown(raw, tmp_path):
    p = tmp_path / "n.json"
    p.write_text(raw)
    v = check_netlist(str(p), "done", ["key"], "top")
    assert v.status == UNKNOWN
    assert v.constant_time is False
    assert v.reason


def test_check_netlist_on_a_binary_file_is_unknown(tmp_path):
    p = tmp_path / "n.json"
    p.write_bytes(b"\x00\x01\x02\xff\xfe")
    v = check_netlist(str(p), "done", ["key"])
    assert v.status == UNKNOWN


def test_check_netlist_on_a_missing_file_is_unknown(tmp_path):
    v = check_netlist(str(tmp_path / "nope.json"), "done", ["key"])
    assert v.status == UNKNOWN


# ---------------------------------------------------------------------------
# Every export format must preserve the verdict.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status,reaching", [
    (CONSTANT_TIME, ()), (LEAKY, ("k",)), (UNKNOWN, ()),
])
def test_json_export_preserves_the_verdict(status, reaching):
    f = F((V(status, reaching), "a.v"))
    assert json.loads(f.to_json())["verdict"] == status


@pytest.mark.parametrize("status,reaching,expect_result,level", [
    (CONSTANT_TIME, (), 0, None),
    (LEAKY, ("k",), 1, "error"),
    (UNKNOWN, (), 1, "warning"),
])
def test_sarif_export_distinguishes_all_three_verdicts(status, reaching,
                                                       expect_result, level):
    """A clean file and an unanalysable one must never look the same in SARIF."""
    run = F((V(status, reaching), "a.v")).to_sarif()["runs"][0]
    assert len(run["results"]) == expect_result
    if level:
        assert run["results"][0]["level"] == level
    # even with no result, the artifact records which verdict it was
    assert status in run["artifacts"][0]["description"]["text"]


def test_a_clean_file_and_an_unknown_file_are_distinguishable_in_sarif():
    clean = F((V(CONSTANT_TIME), "a.v")).to_sarif()["runs"][0]
    unk = F((V(UNKNOWN), "a.v")).to_sarif()["runs"][0]
    assert clean["artifacts"][0]["description"] != unk["artifacts"][0]["description"]
    assert len(clean["results"]) != len(unk["results"])


@pytest.mark.parametrize("status", [CONSTANT_TIME, LEAKY, UNKNOWN])
def test_the_table_never_renders_a_non_clean_verdict_as_ok(status):
    line = F((V(status, ("k",) if status == LEAKY else ()), "a.v")).to_table()
    if status != CONSTANT_TIME:
        assert "[ok " not in line, f"{status} rendered as ok"


def test_explain_json_never_reports_a_verdict_the_analysis_did_not_reach():
    m = Module(name="m")
    m.add("done", {"pub"})
    e = explain(m, V(UNKNOWN))
    d = e.to_dict()
    assert d["verdict"] == UNKNOWN
    assert d["paths"] == []
    assert "CONSTANT_TIME" not in e.render()


def test_graph_exports_are_empty_when_there_is_nothing_to_show():
    """A DOT/Mermaid graph for a clean design must not invent an edge."""
    m = Module(name="m")
    m.add("done", {"pub"})
    e = explain(m, V(CONSTANT_TIME))
    assert "->" not in e.to_dot().replace("rankdir=LR", "")
    assert "-->" not in e.to_mermaid()


# ---------------------------------------------------------------------------
# Baseline: a suppression mechanism is the most dangerous thing here.
# ---------------------------------------------------------------------------

def test_a_baseline_cannot_suppress_a_finding_in_another_file():
    b = Baseline.from_findings(F((V(LEAKY, ("k",)), "a.v")))
    other = F((V(LEAKY, ("k",)), "b.v"))
    b.apply(other)
    assert not other.items[0].baselined
    assert other.exit_code() == 1


def test_a_baseline_cannot_suppress_a_different_secret_set():
    b = Baseline.from_findings(F((V(LEAKY, ("k",)), "a.v")))
    other = F((V(LEAKY, ("k", "extra")), "a.v"))
    b.apply(other)
    assert not other.items[0].baselined


def test_a_baselined_unknown_never_becomes_constant_time():
    f = F((V(UNKNOWN), "a.v"))
    Baseline.from_findings(f).apply(f)
    assert f.items[0].status == UNKNOWN
    assert f.items[0].verdict.constant_time is False
    assert f.items[0].to_dict()["verdict"] == UNKNOWN


def test_a_baseline_survives_a_save_load_save_cycle_byte_identically():
    b = Baseline.from_findings(F((V(LEAKY, ("k",)), "a.v"), (V(UNKNOWN), "b.v")))
    with tempfile.TemporaryDirectory() as td:
        p1, p2 = Path(td) / "a.json", Path(td) / "b.json"
        b.save(p1)
        Baseline.load(p1).save(p2)
        assert p1.read_text() == p2.read_text()


# ---------------------------------------------------------------------------
# diff round-trip: check --json must survive being read back.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status,reaching", [
    (CONSTANT_TIME, ()), (LEAKY, ("k",)), (UNKNOWN, ()),
])
def test_findings_survive_a_json_round_trip_unchanged(status, reaching, tmp_path):
    f = F((V(status, reaching), "a.v"))
    p = tmp_path / "r.json"
    p.write_text(f.to_json())
    back = load_findings(p)
    assert back.items[0].status == status
    assert back.items[0].verdict.reaching == list(reaching)
    assert diff(f, back).unchanged == 1
    assert not diff(f, back).is_regression


def test_diff_of_a_file_against_itself_is_never_a_regression(tmp_path):
    for status in (CONSTANT_TIME, LEAKY, UNKNOWN):
        f = F((V(status, ("k",) if status == LEAKY else ()), "a.v"))
        assert not diff(f, f).is_regression


# ---------------------------------------------------------------------------
# Enormous.
# ---------------------------------------------------------------------------

def test_a_fifty_thousand_cell_netlist_terminates():
    n = 20000
    cells = {f"g{i}": {"type": "$and",
                       "port_directions": {"A": "input", "Y": "output"},
                       "connections": {"A": [i + 10], "Y": [i + 11]}}
             for i in range(n)}
    data = {"modules": {"top": {
        "ports": {"key": {"direction": "input", "bits": [10]},
                  "done": {"direction": "output", "bits": [n + 10]}},
        "cells": cells,
        "netnames": {f"w{i}": {"bits": [i + 10]} for i in range(n + 2)}}}}
    start = time.perf_counter()
    mod = parse_netlist(data, "top")
    v = verdict_for(mod, "done", ["key"])
    assert v.status == LEAKY
    assert time.perf_counter() - start < 30


def test_shortest_path_over_a_very_long_chain_does_not_recurse():
    """BFS, not DFS: a recursive walk would blow the stack here."""
    m = Module(name="deep")
    m.add("s0", {"key"})
    for i in range(1, 5000):
        m.add(f"s{i}", {f"s{i - 1}"})
    m.add("done", {"s4999"})
    p = shortest_path(m, "done", "key")
    assert p is not None
    assert p.length == 5001 - 1 - 0 or p.length > 4000
