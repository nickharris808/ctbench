"""Tests for ctbench: the parser, the reference checker, and the scoring rules."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import ctbench
from ctbench.cli import run_reference
from ctbench.cone import analyse, identifiers, parse
from ctbench.score import load_manifest, score

FIXTURES = Path(ctbench.__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="module")
def manifest():
    return load_manifest()


# --------------------------------------------------------------------------
# Parser units.  Each of the first three is a regression test for a real bug
# that produced a FALSE "constant time" verdict on a genuinely leaky fixture.
# --------------------------------------------------------------------------

def test_guard_conditions_are_dependency_edges():
    """`if (secret) x <= 0;` makes x depend on secret even though it is not on the RHS."""
    src = """
    module m(clk, s, x);
      input clk; input s; output reg x;
      always @(posedge clk) begin
        if (s) x <= 1'b0; else x <= 1'b1;
      end
    endmodule
    """
    m = parse(src)
    assert "s" in m.deps["x"]


def test_net_declaration_assignment_is_parsed():
    """`wire w = expr;` is a continuous assignment; missing it empties the cone."""
    src = """
    module m(a, b, done);
      input a; input b; output done;
      wire fire = a & b;
      assign done = fire;
    endmodule
    """
    m = parse(src)
    assert m.deps["fire"] == {"a", "b"}
    assert m.cone(["done"]) >= {"done", "fire", "a", "b"}


def test_else_if_chain_is_consumed_whole():
    """Statements after the first in a nested else-if must keep their guards."""
    src = """
    module m(clk, g, h, p, q);
      input clk; input g; input h; output reg p; output reg q;
      always @(posedge clk) begin
        if (g) begin
          p <= 1'b0;
        end else if (h) begin
          p <= 1'b1;
          q <= 1'b1;
        end
      end
    endmodule
    """
    m = parse(src)
    # q is assigned second inside the else-if; it must still see both guards.
    assert "h" in m.deps["q"], "guard lost on a non-first statement"
    assert "g" in m.deps["q"]


def test_identifiers_ignores_literals_and_keywords():
    got = identifiers("running & (cnt == 4'd8) | 8'hFF")
    assert got == {"running", "cnt"}


def test_ansi_and_non_ansi_ports_both_parse():
    ansi = parse((FIXTURES / "ct_div_wide.v").read_text())
    non_ansi = parse((FIXTURES / "ct_cmp.v").read_text())
    assert {"clk", "a", "b"} <= set(ansi.inputs)
    assert {"clk", "rst", "start", "x", "y"} <= set(non_ansi.inputs)


def test_multi_signal_declaration_captures_every_name():
    """`input clk, rst, start;` declares three inputs, not one."""
    m = parse("module m(a,b,c); input a, b, c; endmodule")
    assert m.inputs == ["a", "b", "c"]


def test_unknown_observation_raises():
    with pytest.raises(ValueError):
        analyse("module m(a); input a; endmodule", "nope", ["a"])


# --------------------------------------------------------------------------
# The corpus itself.
# --------------------------------------------------------------------------

def test_every_manifest_fixture_exists(manifest):
    for entry in manifest["scored"] + manifest["unscored"]:
        assert (FIXTURES / entry["file"]).is_file(), entry["file"]


def test_manifest_covers_every_fixture_file(manifest):
    listed = {e["file"] for e in manifest["scored"] + manifest["unscored"]}
    on_disk = {p.name for p in FIXTURES.glob("*.v")}
    assert listed == on_disk, f"unlisted: {on_disk - listed}, missing: {listed - on_disk}"


def test_every_pair_has_both_roles(manifest):
    pairs: dict[str, set[str]] = {}
    for e in manifest["scored"]:
        if e.get("pair"):
            pairs.setdefault(e["pair"], set()).add(e["role"])
    for pair, roles in pairs.items():
        assert {"positive", "negative"} <= roles, f"{pair} lacks a matched twin"


def test_reference_checker_is_perfect_on_the_corpus(manifest):
    s = score(run_reference(manifest), manifest)
    assert s.unsound == []
    assert s.imprecise == []
    assert s.correct == s.total == 18
    assert s.pairs_separated == s.pairs_total == 8
    assert s.out_of_remit_ok is True


def test_out_of_remit_control_is_constant_time(manifest):
    """barrett_buggy is functionally wrong but genuinely constant-time."""
    e = next(x for x in manifest["scored"] if x["role"] == "out_of_remit")
    v = analyse((FIXTURES / e["file"]).read_text(), e["observation"], e["secrets"], e["module"])
    assert v.constant_time is True


def test_leaky_verdicts_name_the_reaching_secrets(manifest):
    for e in manifest["scored"]:
        if e["expected"] != "LEAKY":
            continue
        v = analyse((FIXTURES / e["file"]).read_text(), e["observation"], e["secrets"], e["module"])
        assert v.reaching, f"{e['file']}: LEAKY but named no reaching secret"
        assert set(v.reaching) <= set(e["secrets"])


# --------------------------------------------------------------------------
# Scoring rules.
# --------------------------------------------------------------------------

def test_scoring_separates_unsound_from_imprecise(manifest):
    sub = {e["file"]: e["expected"] for e in manifest["scored"]}
    sub["cmp_leaky.v"] = "CONSTANT_TIME"        # unsound: said safe, is leaky
    sub["ct_cmp.v"] = "LEAKY"                   # imprecise: said leaky, is safe
    s = score(sub, manifest)
    assert s.unsound == ["cmp_leaky.v"]
    assert s.imprecise == ["ct_cmp.v"]
    assert s.sound is False


def test_abstention_is_neither_correct_nor_unsound(manifest):
    sub = {e["file"]: e["expected"] for e in manifest["scored"]}
    sub["cmp_leaky.v"] = "UNKNOWN"
    s = score(sub, manifest)
    assert s.abstained == ["cmp_leaky.v"]
    assert s.sound is True
    assert s.correct == 17


def test_crying_wolf_on_the_out_of_remit_control_is_detected(manifest):
    sub = {e["file"]: e["expected"] for e in manifest["scored"]}
    sub["barrett_buggy.v"] = "LEAKY"
    s = score(sub, manifest)
    assert s.out_of_remit_ok is False


def test_missing_entries_are_reported_not_credited(manifest):
    sub = {e["file"]: e["expected"] for e in manifest["scored"]}
    del sub["ct_mul.v"]
    s = score(sub, manifest)
    assert s.missing == ["ct_mul.v"]
    assert s.correct == 17


def test_pair_separation_requires_both_halves_right(manifest):
    sub = {e["file"]: e["expected"] for e in manifest["scored"]}
    sub["mul_leaky.v"] = "CONSTANT_TIME"
    s = score(sub, manifest)
    assert s.pairs_separated == s.pairs_total - 1


def test_bad_verdict_string_rejected(manifest):
    with pytest.raises(ValueError):
        score({"ct_mul.v": "PROBABLY_FINE"}, manifest)


def test_baseline_result_file_matches_a_fresh_run(manifest):
    """The published baseline must not drift from what the code actually does."""
    baseline = json.loads((FIXTURES.parent / "baseline.json").read_text())
    assert baseline["verdicts"] == run_reference(manifest)


# --------------------------------------------------------------------------
# CLI: a pip-installed user has no fixtures/ directory relative to cwd, so a
# bare fixture name must resolve against the installed package.
# --------------------------------------------------------------------------

def test_bundled_fixture_resolves_by_bare_name(manifest):
    from ctbench.cli import resolve

    path, entry = resolve("cmp_leaky.v", manifest)
    assert path.is_file()
    assert entry is not None and entry["secrets"] == ["x", "y"]


def test_resolve_prefers_an_existing_path(tmp_path, manifest):
    from ctbench.cli import resolve

    local = tmp_path / "cmp_leaky.v"
    local.write_text("module cmp_leaky(a); input a; endmodule")
    path, _ = resolve(str(local), manifest)
    assert path == local


def test_resolve_rejects_an_unknown_name(manifest):
    from ctbench.cli import resolve

    with pytest.raises(SystemExit, match="no such file"):
        resolve("not_a_fixture.v", manifest)


def test_cli_check_uses_manifest_secrets_for_a_bundled_fixture(capsys):
    from ctbench.cli import main

    assert main(["check", "cmp_leaky.v"]) == 1          # LEAKY -> exit 1
    out = json.loads(capsys.readouterr().out)
    assert out["verdict"] == "LEAKY"
    assert out["reaching_secrets"] == ["x", "y"]


def test_cli_check_on_a_safe_fixture_exits_zero(capsys):
    from ctbench.cli import main

    assert main(["check", "ct_cmp.v"]) == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "CONSTANT_TIME"


def test_cli_check_requires_secrets_for_an_unlisted_file(tmp_path):
    from ctbench.cli import main

    f = tmp_path / "mine.v"
    f.write_text("module mine(clk, done); input clk; output done; assign done = clk; endmodule")
    with pytest.raises(SystemExit, match="no secrets given"):
        main(["check", str(f)])


def test_cli_fixtures_lists_the_corpus(capsys):
    from ctbench.cli import main

    assert main(["fixtures"]) == 0
    out = capsys.readouterr().out
    assert "cmp_leaky.v" in out and "pcpi_div.v" in out


# --------------------------------------------------------------------------
# Submissions and the leaderboard.
# --------------------------------------------------------------------------

def _valid_payload(manifest, **over):
    from ctbench.leaderboard import make_submission

    verdicts = {e["file"]: e["expected"] for e in manifest["scored"]}
    verdicts.update(over.pop("verdicts", {}))
    return make_submission(verdicts, tool=over.pop("tool", "t"),
                           version=over.pop("version", "1"), **over)


def test_valid_submission_parses(manifest):
    from ctbench.leaderboard import parse_submission

    sub = parse_submission(_valid_payload(manifest), manifest)
    assert sub.tool == "t"
    assert len(sub.verdicts) == 18


def test_submission_must_cover_every_scored_fixture(manifest):
    """Answering only the easy half must not be the cheapest route up the board."""
    from ctbench.leaderboard import InvalidSubmission, parse_submission

    p = _valid_payload(manifest)
    del p["verdicts"]["cmp_leaky.v"]
    with pytest.raises(InvalidSubmission, match="must cover every scored fixture"):
        parse_submission(p, manifest)


def test_abstention_is_the_documented_way_to_decline(manifest):
    from ctbench.leaderboard import parse_submission

    p = _valid_payload(manifest, verdicts={"cmp_leaky.v": "UNKNOWN"})
    sub = parse_submission(p, manifest)
    assert sub.verdicts["cmp_leaky.v"] == "UNKNOWN"


def test_invented_fixture_names_are_rejected(manifest):
    from ctbench.leaderboard import InvalidSubmission, parse_submission

    p = _valid_payload(manifest)
    p["verdicts"]["not_a_fixture.v"] = "LEAKY"
    with pytest.raises(InvalidSubmission, match="not in the benchmark"):
        parse_submission(p, manifest)


def test_verdicts_outside_the_vocabulary_are_rejected(manifest):
    from ctbench.leaderboard import InvalidSubmission, parse_submission

    p = _valid_payload(manifest, verdicts={"ct_mul.v": "PROBABLY"})
    with pytest.raises(InvalidSubmission, match="outside the vocabulary"):
        parse_submission(p, manifest)


def test_missing_required_fields_are_rejected(manifest):
    from ctbench.leaderboard import InvalidSubmission, parse_submission

    p = _valid_payload(manifest)
    del p["tool"]
    with pytest.raises(InvalidSubmission, match="missing required field"):
        parse_submission(p, manifest)


def test_future_submission_version_is_rejected(manifest):
    from ctbench.leaderboard import InvalidSubmission, parse_submission

    p = _valid_payload(manifest)
    p["submission_version"] = 99
    with pytest.raises(InvalidSubmission, match="not supported"):
        parse_submission(p, manifest)


def test_tool_name_must_be_a_plain_identifier(manifest):
    from ctbench.leaderboard import InvalidSubmission, parse_submission

    p = _valid_payload(manifest, tool="<script>alert(1)</script>")
    with pytest.raises(InvalidSubmission, match="plain identifier"):
        parse_submission(p, manifest)


def test_unsound_tool_ranks_below_every_sound_tool(manifest):
    """The ranking rule's whole point: soundness dominates accuracy."""
    from ctbench.leaderboard import build_leaderboard

    # An unsound tool that is otherwise nearly perfect.
    unsound = _valid_payload(manifest, tool="unsound", verdicts={"cmp_leaky.v": "CONSTANT_TIME"})
    # A sound tool that abstains on almost everything.
    timid_verdicts = {e["file"]: "UNKNOWN" for e in manifest["scored"]}
    timid_verdicts["ct_mul.v"] = "CONSTANT_TIME"
    timid = _valid_payload(manifest, tool="timid", verdicts=timid_verdicts)

    board = build_leaderboard([unsound, timid], manifest)
    assert [e.submission.tool for e in board] == ["timid", "unsound"]
    assert board[0].score.sound is True
    assert board[1].score.sound is False


def test_pair_separation_outranks_raw_accuracy(manifest):
    from ctbench.leaderboard import build_leaderboard

    # Both sound. One separates every pair; one abstains on a whole pair but is
    # otherwise identical, so it has fewer correct answers AND fewer pairs.
    perfect = _valid_payload(manifest, tool="perfect")
    abstains = _valid_payload(manifest, tool="abstains",
                              verdicts={"ct_mul.v": "UNKNOWN", "mul_leaky.v": "UNKNOWN"})
    board = build_leaderboard([abstains, perfect], manifest)
    assert [e.submission.tool for e in board] == ["perfect", "abstains"]
    assert board[0].score.pairs_separated > board[1].score.pairs_separated


def test_abstaining_beats_being_wrong(manifest):
    from ctbench.leaderboard import build_leaderboard

    wrong = _valid_payload(manifest, tool="wrong", verdicts={"ct_cmp.v": "LEAKY"})
    unsure = _valid_payload(manifest, tool="unsure", verdicts={"ct_cmp.v": "UNKNOWN"})
    board = build_leaderboard([wrong, unsure], manifest)
    # both are sound; the one that abstained has fewer imprecise verdicts
    assert all(e.score.sound for e in board)
    assert board[0].submission.tool == "unsure"


def test_leaderboard_renders_and_flags_crying_wolf(manifest):
    from ctbench.leaderboard import build_leaderboard, format_leaderboard

    wolf = _valid_payload(manifest, tool="wolf", verdicts={"barrett_buggy.v": "LEAKY"})
    text = format_leaderboard(build_leaderboard([wolf], manifest))
    assert "**wolf**" in text
    assert "Ranked by soundness first" in text


def test_shipped_submissions_are_valid_and_ranked(manifest):
    """The bundled registry must itself validate, and rank the way it claims."""
    from ctbench.leaderboard import build_leaderboard, load_registry

    root = Path(ctbench.__file__).resolve().parent.parent / "submissions"
    board = build_leaderboard(load_registry(root), manifest)
    assert board[0].submission.tool == "ctbench-reference"
    assert board[0].score.sound is True
    assert board[-1].score.sound is False, "the straw tool must rank last, and be unsound"


def test_cli_submit_validate_leaderboard_round_trip(tmp_path, capsys):
    from ctbench.cli import main

    out = tmp_path / "sub.json"
    assert main(["submit", "--tool", "demo", "--tool-version", "0.1", "-o", str(out)]) == 0
    assert main(["validate", str(out)]) == 0
    assert "VALID" in capsys.readouterr().out

    (tmp_path / "reg").mkdir()
    (tmp_path / "reg" / "a.json").write_text(out.read_text())
    assert main(["leaderboard", str(tmp_path / "reg")]) == 0
    assert "demo 0.1" in capsys.readouterr().out


def test_cli_validate_rejects_an_incomplete_submission(tmp_path, capsys, manifest):
    from ctbench.cli import main

    p = _valid_payload(manifest)
    del p["verdicts"]["ct_gcd.v"]
    f = tmp_path / "bad.json"
    f.write_text(json.dumps(p))
    assert main(["validate", str(f)]) == 1
    assert "REJECTED" in capsys.readouterr().out


# --------------------------------------------------------------------------
# Hugging Face dataset export.
# --------------------------------------------------------------------------

def test_export_writes_a_record_per_fixture(tmp_path, manifest):
    from ctbench.export import export

    info = export(tmp_path / "ds", manifest)
    assert info["records"] == 27
    assert info["scored"] == 18
    lines = (tmp_path / "ds" / "corpus.jsonl").read_text().strip().splitlines()
    assert len(lines) == 27


def test_exported_records_inline_the_real_source(tmp_path, manifest):
    from ctbench.export import export

    export(tmp_path / "ds", manifest)
    records = [json.loads(x) for x in
               (tmp_path / "ds" / "corpus.jsonl").read_text().strip().splitlines()]
    by_file = {r["file"]: r for r in records}
    assert "module cmp_leaky" in by_file["cmp_leaky.v"]["source"]
    assert by_file["cmp_leaky.v"]["label"] == "LEAKY"
    assert by_file["cmp_leaky.v"]["secrets"] == ["x", "y"]


def test_unscored_records_carry_a_reason_and_no_label(tmp_path, manifest):
    from ctbench.export import export

    export(tmp_path / "ds", manifest)
    records = [json.loads(x) for x in
               (tmp_path / "ds" / "corpus.jsonl").read_text().strip().splitlines()]
    for r in records:
        if not r["scored"]:
            assert r["label"] is None
            assert r["reason"]


def test_picorv32_derivatives_are_labelled_isc(tmp_path, manifest):
    """Flattening the licence to one value would misstate it."""
    from ctbench.export import ISC_FIXTURES, export

    export(tmp_path / "ds", manifest)
    records = [json.loads(x) for x in
               (tmp_path / "ds" / "corpus.jsonl").read_text().strip().splitlines()]
    for r in records:
        expected = "ISC" if r["file"] in ISC_FIXTURES else "CC-BY-4.0"
        assert r["license"] == expected, r["file"]
    assert sum(1 for r in records if r["license"] == "ISC") == 4


def test_dataset_card_has_valid_front_matter(tmp_path, manifest):
    from ctbench.export import export

    export(tmp_path / "ds", manifest)
    card = (tmp_path / "ds" / "README.md").read_text()
    assert card.startswith("---\n")
    front, _, body = card[4:].partition("\n---\n")
    assert "license:" in front and "cc-by-4.0" in front and "isc" in front
    assert "configs:" in front and "corpus.jsonl" in front
    # counts in the prose must match the data, not be hand-written
    assert "18 scored" in body and "8 matched pairs" in body
    assert "62,206 of 65,536" in body
    assert "never inferred" in body


def test_exported_jsonl_is_one_object_per_line(tmp_path, manifest):
    from ctbench.export import export

    export(tmp_path / "ds", manifest)
    for line in (tmp_path / "ds" / "corpus.jsonl").read_text().strip().splitlines():
        obj = json.loads(line)
        assert set(obj) == {
            "file", "module", "source", "scored", "label", "observation",
            "secrets", "pair", "role", "note", "reason", "license",
        }


def test_cli_export(tmp_path, capsys):
    from ctbench.cli import main

    assert main(["export", str(tmp_path / "out")]) == 0
    out = capsys.readouterr().out
    assert "27 records" in out and "corpus.jsonl" in out
    assert (tmp_path / "out" / "README.md").is_file()
