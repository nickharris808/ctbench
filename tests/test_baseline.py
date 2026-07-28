"""Baselines, and the ways a baseline could quietly become a lie.

A baseline is a suppression mechanism, which makes it the most dangerous feature in
the tool: every bug in it hides a finding. The three properties worth protecting, in
order of how badly they would hurt:

1. **it must not hide a finding it never saw.** Matching on filename would be simpler
   and would silently swallow the next leak in every file anyone ever baselined;
2. **a baselined UNKNOWN stays UNKNOWN.** Acknowledging "we could not tell" must not
   convert it into "it is fine" anywhere it is printed or exported;
3. **a corrupt baseline refuses.** Ignoring an unreadable one silently drops every
   suppression, which turns a green run into a meaningless one.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ctbench.baseline import Baseline, BaselineError
from ctbench.cone import CONSTANT_TIME, LEAKY, UNKNOWN, Verdict
from ctbench.findings import Findings

FIXTURES = Path(__file__).resolve().parent.parent / "ctbench" / "fixtures"


def v(status, module="m", observation="done", reaching=()):
    return Verdict(module=module, observation=observation, secrets=["key"],
                   reaching=list(reaching), cone_size=5, status=status,
                   reason="no verdict" if status == UNKNOWN else None)


def findings(*pairs) -> Findings:
    f = Findings()
    for verdict, path in pairs:
        f.add(verdict, path)
    return f


def _run(*args, cwd=None):
    return subprocess.run([sys.executable, "-m", "ctbench.cli", *args],
                          capture_output=True, text=True, cwd=cwd, check=False)


# ---------------------------------------------------------------------------
# 1. It must not hide a finding it never saw.
# ---------------------------------------------------------------------------

def test_a_different_leak_in_a_baselined_file_is_still_reported():
    """The property that makes filename-based suppression unacceptable."""
    recorded = findings((v(LEAKY, reaching=["key"]), "a.v"))
    b = Baseline.from_findings(recorded)

    same = findings((v(LEAKY, reaching=["key"]), "a.v"))
    b.apply(same)
    assert same.items[0].baselined is True, "the recorded finding should be suppressed"

    different = findings((v(LEAKY, reaching=["key", "nonce"]), "a.v"))
    b.apply(different)
    assert different.items[0].baselined is False, (
        "a leak reaching a different secret set is a different finding and must "
        "not be suppressed"
    )
    assert different.exit_code() == 1


def test_a_leak_on_a_different_observation_is_not_suppressed():
    b = Baseline.from_findings(findings((v(LEAKY, observation="done", reaching=["key"]), "a.v")))
    other = findings((v(LEAKY, observation="valid", reaching=["key"]), "a.v"))
    b.apply(other)
    assert other.items[0].baselined is False


def test_the_same_finding_in_a_different_file_is_not_suppressed():
    b = Baseline.from_findings(findings((v(LEAKY, reaching=["key"]), "a.v")))
    other = findings((v(LEAKY, reaching=["key"]), "b.v"))
    b.apply(other)
    assert other.items[0].baselined is False


def test_baseline_keys_ignore_cone_size_and_reason_text():
    """A refactor that changes cone size must not silently un-suppress."""
    b = Baseline.from_findings(findings((v(LEAKY, reaching=["key"]), "a.v")))
    later = findings((v(LEAKY, reaching=["key"]), "a.v"))
    later.items[0].verdict.cone_size = 900
    b.apply(later)
    assert later.items[0].baselined is True


# ---------------------------------------------------------------------------
# 2. A baselined UNKNOWN stays UNKNOWN.
# ---------------------------------------------------------------------------

def test_a_baselined_unknown_is_never_rewritten_to_constant_time():
    f = findings((v(UNKNOWN), "a.v"))
    Baseline.from_findings(f).apply(f)
    item = f.items[0]
    assert item.baselined is True
    assert item.status == UNKNOWN, "the verdict itself must not change"
    assert item.verdict.constant_time is False
    assert item.to_dict()["verdict"] == UNKNOWN
    assert "still UNKNOWN" in item.baseline_reason


def test_a_baselined_unknown_is_excluded_from_the_exit_code_but_still_counted():
    f = findings((v(UNKNOWN), "a.v"))
    Baseline.from_findings(f).apply(f)
    assert f.exit_code() == 0, "acknowledged findings do not fail the run"
    assert len(f.by_status(UNKNOWN)) == 1, "but it is still an UNKNOWN in the report"
    assert "unknown" in f.summary()


def test_clean_files_are_never_written_into_a_baseline():
    b = Baseline.from_findings(findings(
        (v(CONSTANT_TIME), "a.v"), (v(LEAKY, reaching=["key"]), "b.v")))
    assert len(b) == 1


# ---------------------------------------------------------------------------
# 3. A corrupt or foreign baseline refuses.
# ---------------------------------------------------------------------------

def test_a_corrupt_baseline_refuses_rather_than_suppressing_nothing(tmp_path):
    p = tmp_path / "bl.json"
    p.write_text("{not json")
    with pytest.raises(BaselineError, match="not valid JSON"):
        Baseline.load(p)


def test_a_baseline_from_another_tool_is_rejected(tmp_path):
    p = tmp_path / "bl.json"
    p.write_text(json.dumps({"accepted": []}))
    with pytest.raises(BaselineError, match="not a ctbench baseline"):
        Baseline.load(p)


def test_a_malformed_entry_names_the_index(tmp_path):
    p = tmp_path / "bl.json"
    p.write_text(json.dumps({"schema": "ctbench-baseline/1",
                             "accepted": [{"file": "a.v"}]}))
    with pytest.raises(BaselineError, match="entry 0 is malformed"):
        Baseline.load(p)


def test_a_missing_baseline_says_how_to_make_one(tmp_path):
    with pytest.raises(BaselineError, match="update-baseline"):
        Baseline.load(tmp_path / "nope.json")


def test_round_trip_through_disk_preserves_suppression(tmp_path):
    p = tmp_path / "bl.json"
    recorded = findings((v(LEAKY, reaching=["key"]), "a.v"), (v(UNKNOWN), "b.v"))
    Baseline.from_findings(recorded, reason="triaged 2026-07").save(p)
    again = findings((v(LEAKY, reaching=["key"]), "a.v"), (v(UNKNOWN), "b.v"))
    Baseline.load(p).apply(again)
    assert all(f.baselined for f in again)
    assert again.exit_code() == 0


def test_stale_entries_are_reported():
    b = Baseline.from_findings(findings((v(LEAKY, reaching=["key"]), "gone.v")))
    now = findings((v(CONSTANT_TIME), "gone.v"))
    b.apply(now)
    assert len(b.stale(now)) == 1


# ---------------------------------------------------------------------------
# End to end through the CLI.
# ---------------------------------------------------------------------------

@pytest.fixture
def workdir(tmp_path):
    (tmp_path / "leaky.v").write_text((FIXTURES / "cmp_leaky.v").read_text())
    return tmp_path


def test_cli_baseline_makes_a_failing_run_pass(workdir):
    sec = ["--secret", "x", "--secret", "y"]
    assert _run("check", "leaky.v", *sec, cwd=workdir).returncode == 1

    r = _run("check", "leaky.v", *sec, "--baseline", "bl.json", "--update-baseline",
             cwd=workdir)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (workdir / "bl.json").is_file()

    after = _run("check", "leaky.v", *sec, "--baseline", "bl.json", cwd=workdir)
    assert after.returncode == 0, after.stdout + after.stderr
    assert "suppressed" in after.stderr


def test_cli_reports_a_corrupt_baseline_instead_of_ignoring_it(workdir):
    (workdir / "bad.json").write_text("{{{")
    r = _run("check", "leaky.v", "--secret", "x", "--secret", "y",
             "--baseline", "bad.json", cwd=workdir)
    assert r.returncode == 2
    assert "not valid JSON" in r.stderr


def test_cli_marks_baselined_rows_in_the_table(workdir):
    (workdir / "clean.v").write_text((FIXTURES / "ct_cmp.v").read_text())
    sec = ["--secret", "x", "--secret", "y"]
    _run("check", "leaky.v", "clean.v", *sec, "--baseline", "bl.json",
         "--update-baseline", cwd=workdir)
    out = _run("check", "leaky.v", "clean.v", *sec, "--baseline", "bl.json",
               cwd=workdir).stdout
    assert "[baselined]" in out
