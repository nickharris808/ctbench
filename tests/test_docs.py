"""The documentation must describe the tool that actually exists.

Docs rot silently and in the worst direction: a README keeps promising a flag after
it is renamed, or quotes an error message that has since been reworded, and the
reader concludes the tool is broken when it is the prose that is stale. Writing this
file caught three real fabrications in the tutorial — a fixture listing in the wrong
order, an invented `cone_size` of 11 where the tool prints 6, and a whole paragraph
of reasoning built on that invented number.

These tests do not check prose. They check that every *claim with a truth value* —
a documented flag, a quoted error message, a stated exit code, a cross-link — still
matches the code.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "ctbench" / "fixtures"
DOCS = ["README.md", "TUTORIAL.md", "SCOPE.md", "TROUBLESHOOTING.md", "CLI.md"]


@pytest.fixture(scope="module")
def docs() -> dict[str, str]:
    return {d: (ROOT / d).read_text() for d in DOCS if (ROOT / d).is_file()}


def _run(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "ctbench.cli", *args],
        capture_output=True, text=True, cwd=cwd or ROOT, check=False,
    )


def test_every_documented_file_exists():
    for d in DOCS:
        assert (ROOT / d).is_file(), f"{d} is referenced by the doc set but missing"


def test_relative_links_between_docs_resolve(docs):
    """A broken link in the docs is the cheapest possible own goal."""
    broken = [
        f"{name} -> {target}"
        for name, text in docs.items()
        for target in re.findall(r"\]\((?!https?://|#)([^)#]+)[^)]*\)", text)
        if not (ROOT / target).exists()
    ]
    assert not broken, "broken relative links: " + ", ".join(broken)


# ---------------------------------------------------------------------------
# Documented CLI surface.
# ---------------------------------------------------------------------------

def test_every_subcommand_named_in_cli_md_exists(docs):
    """`ctbench <cmd> --help` must succeed for each documented command."""
    if "CLI.md" not in docs:
        pytest.skip("no CLI.md")
    documented = set(re.findall(r"^### `ctbench (\w[\w-]*)", docs["CLI.md"], re.M))
    assert documented, "CLI.md documents no commands"
    for cmd in sorted(documented):
        r = _run(cmd, "--help")
        assert r.returncode == 0, f"documented command {cmd!r} does not exist"


def test_every_documented_check_flag_is_accepted(docs):
    if "CLI.md" not in docs:
        pytest.skip("no CLI.md")
    helptext = _run("check", "--help").stdout
    for flag in ("--observation", "--secret", "--module", "--json", "--sarif"):
        assert flag in helptext, f"{flag} is documented but not in `check --help`"


def test_documented_exit_codes_are_the_real_ones(tmp_path):
    """0 clean, 1 leaky, 2 unknown — and 2 must outrank 1."""
    (tmp_path / "leaky.v").write_text((FIXTURES / "cmp_leaky.v").read_text())
    (tmp_path / "clean.v").write_text((FIXTURES / "ct_cmp.v").read_text())
    (tmp_path / "hier.v").write_text(
        "module top (clk, key, done);\n  input clk; input [7:0] key; output done;\n"
        "  child u (.clk(clk), .key(key), .done(done));\nendmodule\n"
    )
    sec = ["--secret", "x", "--secret", "y", "--secret", "key"]
    assert _run("check", "clean.v", *sec, cwd=tmp_path).returncode == 0
    assert _run("check", "leaky.v", *sec, cwd=tmp_path).returncode == 1
    assert _run("check", "hier.v", *sec, cwd=tmp_path).returncode == 2
    # 2 outranks 1 when both are present
    assert _run("check", "leaky.v", "hier.v", *sec, cwd=tmp_path).returncode == 2


# ---------------------------------------------------------------------------
# Quoted error messages.
# ---------------------------------------------------------------------------

def test_quoted_refusal_phrases_are_really_emitted(tmp_path):
    """TROUBLESHOOTING quotes these; if the wording drifts, the doc misleads."""
    (tmp_path / "hier.v").write_text(
        "module top (clk, key, done);\n  input clk; input [7:0] key; output done;\n"
        "  child u (.clk(clk), .key(key), .done(done));\nendmodule\n"
    )
    out = _run("check", "hier.v", "--secret", "key", cwd=tmp_path)
    both = out.stdout + out.stderr
    assert "outside the supported Verilog subset" in both
    assert "no verdict is returned" in both


def test_missing_secrets_message_matches_the_docs(tmp_path):
    (tmp_path / "a.v").write_text((FIXTURES / "cmp_leaky.v").read_text())
    out = _run("check", "a.v", cwd=tmp_path)
    both = out.stdout + out.stderr
    assert "never inferred" in both
    assert "ctbench fixtures" in both


def test_undriven_observation_message_matches_the_docs(tmp_path):
    (tmp_path / "n.v").write_text(
        "module top(clk, x, done); input clk; input [7:0] x; output done; endmodule"
    )
    out = _run("check", "n.v", "--secret", "x", cwd=tmp_path)
    both = out.stdout + out.stderr
    assert "nothing in the parsed source drives it" in both


def test_module_typo_lists_the_available_modules(tmp_path):
    """Documented as naming what the file defines, rather than a bare failure."""
    (tmp_path / "a.v").write_text((FIXTURES / "cmp_leaky.v").read_text())
    out = _run("check", "a.v", "--module", "nope", "--secret", "x", cwd=tmp_path)
    both = out.stdout + out.stderr
    assert "This file defines" in both
    assert "cmp_leaky" in both
    assert "Traceback" not in both, "a user typo must not produce a traceback"


def test_no_module_found_is_a_refusal_not_a_traceback(tmp_path):
    (tmp_path / "e.v").write_text("")
    out = _run("check", "e.v", "--secret", "x", cwd=tmp_path)
    assert "Traceback" not in (out.stdout + out.stderr)
    assert "no module found" in (out.stdout + out.stderr)


# ---------------------------------------------------------------------------
# Claims about the corpus and the subset.
# ---------------------------------------------------------------------------

def test_documented_fixture_count_matches_the_manifest(docs):
    from ctbench.score import load_manifest

    man = load_manifest()
    total = len(man["scored"]) + len(man["unscored"])
    for name, text in docs.items():
        for claimed in re.findall(r"all (\d+) (?:bundled )?fixtures", text):
            assert int(claimed) == total, f"{name} claims {claimed} fixtures, there are {total}"
        for claimed in re.findall(r"Those (\d+) files ship", text):
            assert int(claimed) == total, f"{name} claims {claimed} files, there are {total}"


def test_scope_lists_exactly_the_constructs_the_scanner_refuses(docs):
    """A construct refused by the code but absent from SCOPE.md is an unpleasant surprise."""
    if "SCOPE.md" not in docs:
        pytest.skip("no SCOPE.md")
    from ctbench.cone import _UNSUPPORTED

    scope = docs["SCOPE.md"].lower()
    for name, _pat, _literal in _UNSUPPORTED:
        head = name.split()[0].lower()          # "module", "for", "generate", ...
        assert head in scope, f"SCOPE.md never mentions the refused construct {name!r}"


def test_docs_never_claim_constant_time_is_unconditionally_conservative(docs):
    """The pre-fix wording; it is only true within the supported subset."""
    for name, text in docs.items():
        for m in re.finditer(r"[^.]*CONSTANT_TIME` is conservative[^.]*\.", text):
            sentence = m.group(0)
            assert "subset" in sentence or "there" in sentence, (
                f"{name} says CONSTANT_TIME is conservative without the subset "
                f"qualifier: {sentence.strip()!r}"
            )


def test_docs_state_that_unknown_is_not_a_pass(docs):
    joined = " ".join(docs.values())
    assert "UNKNOWN` is not a pass" in joined or "UNKNOWN is not a pass" in joined


def test_sibling_tools_are_cross_linked(docs):
    """The portfolio should read as one ecosystem, not five orphans."""
    joined = " ".join(docs.values())
    for repo in ("ct-mask", "patchproof", "ct-audit-action", "hw-verify-mcp"):
        assert f"github.com/nickharris808/{repo}" in joined, f"no cross-link to {repo}"
    assert "huggingface.co/spaces/nickh007/hw-verify" in joined
