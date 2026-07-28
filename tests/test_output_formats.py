"""Multi-file checking and machine-readable output.

A verdict printed to a CI log is read once, by whoever opened the run. The same
verdict as SARIF becomes a pull-request annotation and an entry in the security tab.
These tests pin the properties that make that trustworthy rather than merely present.

The load-bearing one is `test_sarif_reports_unknown_as_a_warning`: the obvious SARIF
reading is "results are findings", under which a file that could not be analysed
produces nothing at all — indistinguishable, to a reviewer, from a clean pass. That
is the exact confusion the refusal machinery exists to prevent, so UNKNOWN has to
survive the trip into SARIF.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ctbench.sarif import RULES, to_sarif

FIXTURES = Path(__file__).resolve().parent.parent / "ctbench" / "fixtures"

LEAKY = {"file": "rtl/a.v", "verdict": "LEAKY", "observation": "done",
         "secrets": ["x"], "reaching_secrets": ["x", "y"], "cone_size": 9}
CLEAN = {"file": "rtl/b.v", "verdict": "CONSTANT_TIME", "observation": "done",
         "secrets": ["x"], "reaching_secrets": [], "cone_size": 11}
UNK = {"file": "rtl/c.v", "verdict": "UNKNOWN", "observation": "done",
       "secrets": ["x"], "reaching_secrets": [], "cone_size": 0,
       "reason": "line 5: module instantiation is outside the supported Verilog subset"}


def _run(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "ctbench.cli", *args],
        capture_output=True, text=True, cwd=cwd, check=False,
    )


# ---------------------------------------------------------------------------
# SARIF shape.
# ---------------------------------------------------------------------------

def test_sarif_is_valid_2_1_0_with_the_required_keys():
    log = to_sarif([LEAKY, CLEAN, UNK])
    assert log["version"] == "2.1.0"
    assert log["$schema"].endswith("sarif-schema-2.1.0.json")
    run = log["runs"][0]
    assert run["tool"]["driver"]["name"] == "ctbench"
    for r in run["results"]:
        assert r["ruleId"] and r["level"] and r["message"]["text"]
        assert r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]


def test_every_result_rule_index_points_at_its_own_rule():
    """A wrong ruleIndex silently mislabels findings in the GitHub UI."""
    log = to_sarif([LEAKY, UNK])
    rules = log["runs"][0]["tool"]["driver"]["rules"]
    for r in log["runs"][0]["results"]:
        assert rules[r["ruleIndex"]]["id"] == r["ruleId"]


def test_a_leak_is_an_error_naming_the_reaching_secrets():
    r = to_sarif([LEAKY])["runs"][0]["results"][0]
    assert r["ruleId"] == "CT001"
    assert r["level"] == "error"
    assert "x, y" in r["message"]["text"]


def test_sarif_reports_unknown_as_a_warning():
    """Silence would read as a pass — the whole point is that it must not."""
    results = to_sarif([UNK])["runs"][0]["results"]
    assert len(results) == 1, "an unanalysable file must not vanish from the report"
    r = results[0]
    assert r["ruleId"] == "CT002"
    assert r["level"] == "warning"
    assert "NOT been shown to be constant-time" in r["message"]["text"]


def test_unknown_result_is_located_at_the_offending_line():
    """A warning on line 1 of a 400-line file helps nobody."""
    r = to_sarif([UNK])["runs"][0]["results"][0]
    assert r["locations"][0]["physicalLocation"]["region"]["startLine"] == 5


def test_a_clean_file_produces_no_result_but_is_still_listed():
    """'Checked and clean' must be distinguishable from 'never looked at'."""
    run = to_sarif([CLEAN])["runs"][0]
    assert run["results"] == []
    uris = [a["location"]["uri"] for a in run["artifacts"]]
    assert "rtl/b.v" in uris
    assert "CONSTANT_TIME" in run["artifacts"][0]["description"]["text"]


def test_rules_carry_help_text_that_states_the_fix():
    for rule in RULES:
        assert rule["help"]["text"]
        assert rule["fullDescription"]["text"]
        assert rule["defaultConfiguration"]["level"] in ("error", "warning", "note")


# ---------------------------------------------------------------------------
# The CLI end to end.
# ---------------------------------------------------------------------------

@pytest.fixture
def workdir(tmp_path):
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "leaky.v").write_text((FIXTURES / "cmp_leaky.v").read_text())
    (rtl / "clean.v").write_text((FIXTURES / "ct_cmp.v").read_text())
    (rtl / "hier.v").write_text(
        "module top (clk, key, done);\n"
        "    input clk;\n"
        "    input [7:0] key;\n"
        "    output done;\n"
        "    child u_child (.clk(clk), .key(key), .done(done));\n"
        "endmodule\n"
    )
    return tmp_path


def test_check_accepts_several_files_at_once(workdir):
    r = _run("check", "rtl/leaky.v", "rtl/clean.v", "--secret", "x", "--secret", "y",
             cwd=workdir)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "rtl/leaky.v" in r.stdout and "rtl/clean.v" in r.stdout
    assert "LEAKY" in r.stdout


def test_exit_code_2_wins_over_1_when_anything_is_unknown(workdir):
    """A caller guarding only against exit 1 must not be satisfied by 'we could not tell'."""
    r = _run("check", "rtl/leaky.v", "rtl/hier.v", "--secret", "x", "--secret", "y",
             "--secret", "key", cwd=workdir)
    assert r.returncode == 2, r.stdout + r.stderr


def test_all_clean_exits_zero(workdir):
    r = _run("check", "rtl/clean.v", "--secret", "x", "--secret", "y", cwd=workdir)
    assert r.returncode == 0, r.stdout + r.stderr


def test_sarif_flag_emits_parseable_sarif_with_relative_uris(workdir):
    """Absolute build-machine paths resolve to nothing on GitHub."""
    r = _run("check", "rtl/leaky.v", "rtl/hier.v", "--secret", "x", "--secret", "y",
             "--secret", "key", "--sarif", cwd=workdir)
    log = json.loads(r.stdout)
    uris = [
        x["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        for x in log["runs"][0]["results"]
    ]
    assert uris, "no results emitted"
    for u in uris:
        assert not u.startswith("/"), f"absolute URI in SARIF: {u}"
        assert u.startswith("rtl/")


def test_json_flag_emits_a_list_for_several_files(workdir):
    r = _run("check", "rtl/leaky.v", "rtl/clean.v", "--secret", "x", "--secret", "y",
             "--json", cwd=workdir)
    d = json.loads(r.stdout)
    assert isinstance(d, list) and len(d) == 2


def test_single_file_still_emits_one_object(workdir):
    """The documented single-file output shape must not change under the new flag."""
    r = _run("check", "rtl/leaky.v", "--secret", "x", "--secret", "y", cwd=workdir)
    d = json.loads(r.stdout)
    assert isinstance(d, dict)
    assert d["verdict"] == "LEAKY"


def test_missing_secrets_explains_why_they_are_not_inferred(workdir):
    r = _run("check", "rtl/leaky.v", cwd=workdir)
    assert r.returncode != 0
    msg = r.stdout + r.stderr
    assert "never inferred" in msg
    assert "--secret" in msg
    assert "ctbench fixtures" in msg
