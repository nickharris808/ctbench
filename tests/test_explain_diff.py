"""Witness paths and regression diffing.

`explain` matters because the analysis over-approximates: some LEAKY verdicts are
paths that cannot be taken at run time, and without the path a user cannot tell those
from real ones. The tests here mostly check that a path is a *real* path — every
consecutive pair is an actual dependency edge — because a plausible-looking but wrong
path would be worse than none.

`diff` matters because a repo-wide report gets ignored and a this-PR-broke-it report
gets fixed. Its load-bearing test is the coverage-loss one: a file that stopped being
analysable reports no leak, so a naive diff calls that an improvement. It is the
opposite, and treating it as a regression is the whole point.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ctbench.cone import CONSTANT_TIME, LEAKY, UNKNOWN, Verdict, parse, verdict_for
from ctbench.diff import diff, load_findings
from ctbench.explain import all_paths, explain, shortest_path
from ctbench.findings import Findings

FIXTURES = Path(__file__).resolve().parent.parent / "ctbench" / "fixtures"


def _run(*args, cwd=None):
    return subprocess.run([sys.executable, "-m", "ctbench.cli", *args],
                          capture_output=True, text=True, cwd=cwd, check=False)


@pytest.fixture(scope="module")
def leaky():
    src = (FIXTURES / "cmp_leaky.v").read_text()
    mod = parse(src)
    return mod, verdict_for(mod, "done", ["x", "y"])


# ---------------------------------------------------------------------------
# A reported path must be a real path.
# ---------------------------------------------------------------------------

def test_every_step_of_a_path_is_a_real_dependency_edge(leaky):
    """A plausible but fabricated path would be worse than no path at all."""
    mod, v = leaky
    e = explain(mod, v)
    assert e.paths, "a LEAKY verdict must produce at least one path"
    for p in e.paths:
        for src, dst in zip(p.signals, p.signals[1:], strict=False):
            assert src in mod.deps.get(dst, set()), (
                f"{src} -> {dst} is reported as an edge but {dst} does not depend "
                f"on {src}"
            )


def test_a_path_starts_at_the_secret_and_ends_at_the_observation(leaky):
    mod, v = leaky
    for p in explain(mod, v).paths:
        assert p.signals[0] == p.secret
        assert p.signals[-1] == v.observation


def test_there_is_a_path_for_every_reaching_secret(leaky):
    mod, v = leaky
    e = explain(mod, v)
    assert {p.secret for p in e.paths} == set(v.reaching)


def test_shortest_path_really_is_shortest(leaky):
    mod, v = leaky
    for secret in v.reaching:
        short = shortest_path(mod, "done", secret)
        others = all_paths(mod, "done", secret, limit=8)
        assert short is not None
        assert all(short.length <= o.length for o in others)


def test_no_path_when_the_secret_does_not_reach():
    src = (FIXTURES / "ct_cmp.v").read_text()
    mod = parse(src)
    assert shortest_path(mod, "done", "x") is None


def test_all_paths_is_bounded():
    """Unbounded enumeration would hang on exactly the designs that need it."""
    mod = parse((FIXTURES / "cmp_leaky.v").read_text())
    assert len(all_paths(mod, "done", "x", limit=2)) <= 2


def test_paths_never_contain_a_cycle():
    mod = parse((FIXTURES / "cmp_leaky.v").read_text())
    for p in all_paths(mod, "done", "x", limit=8):
        assert len(set(p.signals)) == len(p.signals)


# ---------------------------------------------------------------------------
# What an explanation says for the non-leaky verdicts.
# ---------------------------------------------------------------------------

def test_a_clean_verdict_explains_that_a_path_would_be_the_finding():
    mod = parse((FIXTURES / "ct_cmp.v").read_text())
    e = explain(mod, verdict_for(mod, "done", ["x", "y"]))
    assert e.paths == []
    assert "CONSTANT_TIME" in e.render()


def test_an_unknown_verdict_explains_that_there_is_no_graph_to_trace():
    v = Verdict(module="?", observation="done", secrets=["k"], reaching=[],
                cone_size=0, status=UNKNOWN, reason="module instantiation ...")
    from ctbench.explain import Explanation
    text = Explanation(verdict=v).render()
    assert "UNKNOWN" in text
    assert "no path to show" in text
    assert "CONSTANT_TIME" not in text, "an UNKNOWN must not render like a pass"


def test_graph_exports_contain_every_reported_edge(leaky):
    mod, v = leaky
    e = explain(mod, v)
    dot, mermaid = e.to_dot(), e.to_mermaid()
    for p in e.paths:
        for a, b in zip(p.signals, p.signals[1:], strict=False):
            assert f'"{a}" -> "{b}"' in dot
        for s in p.signals:
            assert s in mermaid


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------

def _f(status, file="a.v", reaching=(), observation="done"):
    fs = Findings()
    fs.add(Verdict(module="m", observation=observation, secrets=["k"],
                   reaching=list(reaching), cone_size=3, status=status,
                   reason="no verdict" if status == UNKNOWN else None), file)
    return fs


def test_a_new_leak_is_introduced():
    d = diff(_f(CONSTANT_TIME), _f(LEAKY, reaching=["k"]))
    assert len(d.introduced) == 1
    assert d.is_regression


def test_a_fixed_leak_is_not_a_regression():
    d = diff(_f(LEAKY, reaching=["k"]), _f(CONSTANT_TIME))
    assert len(d.fixed) == 1
    assert not d.is_regression
    assert d.exit_code() == 0


def test_losing_coverage_counts_as_a_regression():
    """The case a naive diff gets backwards.

    The file stopped being analysable, so it reports no leak — which looks like an
    improvement and is the opposite of one.
    """
    d = diff(_f(CONSTANT_TIME), _f(UNKNOWN))
    assert len(d.lost_coverage) == 1
    assert d.introduced == []
    assert d.is_regression, "a file that stopped being checked is not an improvement"
    assert "no longer being checked" in d.render()


def test_gaining_coverage_is_not_a_regression():
    d = diff(_f(UNKNOWN), _f(CONSTANT_TIME))
    assert len(d.gained_coverage) == 1
    assert not d.is_regression


def test_a_leak_that_moves_is_neither_introduced_nor_fixed():
    d = diff(_f(LEAKY, reaching=["k"]), _f(LEAKY, reaching=["other"]))
    assert d.introduced == [] and d.fixed == []
    assert len(d.changed) == 1
    assert d.is_regression


def test_identical_runs_report_no_change():
    d = diff(_f(LEAKY, reaching=["k"]), _f(LEAKY, reaching=["k"]))
    assert d.unchanged == 1
    assert not d.is_regression
    assert "No change" in d.render()


def test_added_and_removed_files_are_tracked():
    before, after = _f(CONSTANT_TIME, file="a.v"), _f(CONSTANT_TIME, file="b.v")
    d = diff(before, after)
    assert [f.file for f in d.added_files] == ["b.v"]
    assert [f.file for f in d.removed_files] == ["a.v"]


def test_markdown_output_marks_a_regression():
    md = diff(_f(CONSTANT_TIME), _f(LEAKY, reaching=["k"])).to_markdown()
    assert "regression" in md.lower()
    assert "introduced" in md


# ---------------------------------------------------------------------------
# End to end.
# ---------------------------------------------------------------------------

@pytest.fixture
def workdir(tmp_path):
    (tmp_path / "leaky.v").write_text((FIXTURES / "cmp_leaky.v").read_text())
    (tmp_path / "clean.v").write_text((FIXTURES / "ct_cmp.v").read_text())
    return tmp_path


def test_cli_explain_prints_a_path(workdir):
    r = _run("explain", "leaky.v", "--secret", "x", "--secret", "y", cwd=workdir)
    assert r.returncode == 1
    assert "LEAKY" in r.stdout
    assert "xr" in r.stdout, "the intermediate signal should appear in the path"


def test_cli_explain_emits_mermaid_and_dot(workdir):
    m = _run("explain", "leaky.v", "--secret", "x", "--mermaid", cwd=workdir).stdout
    assert m.startswith("flowchart LR")
    d = _run("explain", "leaky.v", "--secret", "x", "--dot", cwd=workdir).stdout
    assert d.startswith("digraph witness")


def test_cli_explain_refuses_what_check_refuses(workdir):
    """The abstention has to survive into the new command."""
    (workdir / "hier.v").write_text(
        "module top(clk,key,done); input clk; input [7:0] key; output done;\n"
        "  child u(.clk(clk),.key(key),.done(done));\nendmodule\n"
    )
    r = _run("explain", "hier.v", "--secret", "key", cwd=workdir)
    assert r.returncode == 2
    assert "UNKNOWN" in r.stderr
    assert "LEAKY" not in r.stdout and "CONSTANT_TIME" not in r.stdout


def test_cli_diff_round_trips_through_check_json(workdir):
    before = workdir / "before.json"
    after = workdir / "after.json"
    r1 = _run("check", "clean.v", "--secret", "x", "--secret", "y", cwd=workdir)
    before.write_text(r1.stdout)
    r2 = _run("check", "leaky.v", "--secret", "x", "--secret", "y", cwd=workdir)
    after.write_text(r2.stdout)

    # different files, so this is an add/remove rather than a change
    d = diff(load_findings(before), load_findings(after))
    assert len(d.added_files) == 1 and len(d.removed_files) == 1

    out = _run("diff", "before.json", "after.json", "--json", cwd=workdir)
    assert json.loads(out.stdout)["regression"] is False


def test_cli_diff_on_unreadable_input_exits_2(workdir):
    (workdir / "bad.json").write_text("{{{")
    r = _run("diff", "bad.json", "bad.json", cwd=workdir)
    assert r.returncode == 2
    assert "cannot read" in r.stderr
