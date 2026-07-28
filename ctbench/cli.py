"""ctbench command line: run the reference checker, or score someone else's tool."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .cone import UNKNOWN, check
from .export import export as export_dataset
from .leaderboard import (
    InvalidSubmission,
    build_leaderboard,
    format_leaderboard,
    load_registry,
    make_submission,
    parse_submission,
)
from .sarif import to_sarif
from .score import format_report, load_manifest, score

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def run_reference(manifest: dict, fixtures: Path = FIXTURES) -> dict[str, str]:
    """The bundled baseline: a syntactic cone-of-influence checker."""
    out: dict[str, str] = {}
    for entry in manifest["scored"]:
        src = (fixtures / entry["file"]).read_text()
        v = check(src, entry["observation"], entry["secrets"], entry["module"])
        out[entry["file"]] = v.status
    return out


def _cmd_run(args) -> int:
    man = load_manifest(args.manifest)
    sub = run_reference(man)
    if args.json:
        print(json.dumps(sub, indent=2))
        return 0
    for entry in man["scored"]:
        f = entry["file"]
        mark = "ok " if sub[f] == entry["expected"] else "BAD"
        print(f"  [{mark}] {f:<26} {sub[f]:<14} expected {entry['expected']}")
    return 0


def _cmd_score(args) -> int:
    man = load_manifest(args.manifest)
    sub = json.loads(Path(args.submission).read_text()) if args.submission else run_reference(man)
    s = score(sub, man)
    if args.json:
        print(json.dumps(s.to_dict(), indent=2))
    else:
        print(format_report(s))
    # A tool that is unsound fails the run; imprecision alone does not.
    return 0 if s.sound else 1


def resolve(target: str, manifest: dict) -> tuple[Path, dict | None]:
    """Resolve `target` to a file, falling back to a bundled fixture by name.

    A pip-installed user has no `ctbench/fixtures/` directory relative to their
    working directory, so a bare fixture name has to resolve against the installed
    package or the documented examples do not work.
    """
    p = Path(target)
    if p.is_file():
        entry = next(
            (e for e in manifest["scored"] + manifest["unscored"] if e["file"] == p.name), None
        )
        return p, entry
    bundled = FIXTURES / Path(target).name
    if bundled.is_file():
        entry = next(
            (e for e in manifest["scored"] + manifest["unscored"]
             if e["file"] == bundled.name), None
        )
        return bundled, entry
    raise SystemExit(
        f"ctbench: no such file {target!r}, and no bundled fixture of that name.\n"
        f"         bundled fixtures live in {FIXTURES}"
    )


def _check_one(target: str, man: dict, args) -> dict:
    """Resolve one target and check it, returning the verdict dict plus its path."""
    path, entry = resolve(target, man)
    observation = args.observation
    secrets = list(args.secret)
    module = args.module
    # For a bundled fixture, the manifest already records the observation signal
    # and the declared secrets, so they need not be retyped.
    if entry:
        observation = observation or entry.get("observation")
        secrets = secrets or list(entry.get("secrets", []))
        module = module or entry.get("module")
    observation = observation or "done"
    if not secrets:
        raise SystemExit(
            f"ctbench: no secrets given for {path.name}. Secrets are a specification\n"
            f"         choice and are never inferred — guessing which inputs are\n"
            f"         sensitive would produce confident verdicts about the wrong\n"
            f"         property.\n"
            f"         Pass --secret NAME (repeatable), or name a bundled fixture\n"
            f"         whose secrets the manifest already records (ctbench fixtures)."
        )
    d = check(path.read_text(), observation, secrets, module).to_dict()
    # Relative to the working directory when it is under it. SARIF consumers resolve
    # artifact URIs against the repository root, so an absolute path from the build
    # machine points at nothing on GitHub — and it leaks the builder's directory
    # layout into a file that gets uploaded.
    try:
        d["file"] = str(path.resolve().relative_to(Path.cwd()))
    except ValueError:
        d["file"] = path.name if path.is_absolute() else str(path)
    return d


def _cmd_check(args) -> int:
    man = load_manifest(args.manifest)
    results = [_check_one(t, man, args) for t in args.file]

    if args.sarif:
        print(json.dumps(to_sarif(results), indent=2))
    elif args.json or len(results) == 1:
        print(json.dumps(results[0] if len(results) == 1 else results, indent=2))
    else:
        for d in results:
            mark = {"CONSTANT_TIME": "ok     ", "LEAKY": "LEAKY  ", "UNKNOWN": "UNKNOWN"}[d["verdict"]]
            extra = ", ".join(d["reaching_secrets"]) or ("no verdict" if d["verdict"] == UNKNOWN else "—")
            print(f"  [{mark}] {d['file']:<40} {extra}")

    for d in results:
        if d["verdict"] == UNKNOWN and not (args.json or args.sarif):
            print(f"\nUNKNOWN — no verdict for {d['file']}.\n{d.get('reason', '')}", file=sys.stderr)

    # Worst verdict wins, and UNKNOWN outranks LEAKY because "we could not tell"
    # must not be satisfiable by a caller that only guards against exit 1.
    if any(d["verdict"] == UNKNOWN for d in results):
        return 2
    return 0 if all(d["verdict"] == "CONSTANT_TIME" for d in results) else 1


def _cmd_fixtures(args) -> int:
    man = load_manifest(args.manifest)
    print(f"bundled fixtures ({FIXTURES}):\n")
    for e in man["scored"]:
        print(f"  {e['file']:<26} scored    expected {e['expected']}")
    for e in man["unscored"]:
        print(f"  {e['file']:<26} unscored")
    return 0


def _cmd_submit(args) -> int:
    """Turn a set of verdicts into a submission payload."""
    man = load_manifest(args.manifest)
    verdicts = (
        json.loads(Path(args.verdicts).read_text()) if args.verdicts else run_reference(man)
    )
    payload = make_submission(
        verdicts, tool=args.tool, version=args.tool_version,
        url=args.url or "", method=args.method or "", notes=args.notes or "",
    )
    try:
        parse_submission(payload, man)
    except InvalidSubmission as exc:
        print(f"ctbench: submission is not valid: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(payload, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(text)
        print(f"wrote {args.output}")
    else:
        print(text, end="")
    return 0


def _cmd_validate(args) -> int:
    man = load_manifest(args.manifest)
    try:
        sub = parse_submission(json.loads(Path(args.submission).read_text()), man)
    except InvalidSubmission as exc:
        print(f"REJECTED  {exc}")
        return 1
    s = score(sub.verdicts, man)
    print(f"VALID     {sub.tool} {sub.version}: covers all {s.total} scored fixtures")
    print(format_report(s))
    return 0


def _cmd_leaderboard(args) -> int:
    man = load_manifest(args.manifest)
    try:
        entries = build_leaderboard(load_registry(args.path), man)
    except InvalidSubmission as exc:
        print(f"ctbench: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps([e.to_dict() for e in entries], indent=2))
    else:
        print(format_leaderboard(entries))
    return 0


def _cmd_export(args) -> int:
    """Emit a Hugging Face-loadable dataset: JSONL plus a dataset card."""
    info = export_dataset(args.out, load_manifest(args.manifest))
    print(f"wrote {info['records']} records ({info['scored']} scored) to {info['directory']}")
    for f in info["files"]:
        print(f"  {f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ctbench", description=__doc__)
    p.add_argument("--manifest", help="path to a manifest.json")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run the bundled reference checker over every fixture")
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=_cmd_run)

    s = sub.add_parser("score", help="score a submission (default: the reference checker)")
    s.add_argument("submission", nargs="?", help="JSON file: fixture -> verdict")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_cmd_score)

    c = sub.add_parser(
        "check", help="check Verilog files, or bundled fixtures by name")
    c.add_argument("file", nargs="+",
                   help="one or more .v paths, or names of bundled fixtures")
    c.add_argument("--observation", help="completion signal (default: from manifest, else 'done')")
    c.add_argument("--secret", action="append", default=[],
                   help="a secret input; repeatable. Defaults to the manifest for a bundled fixture")
    c.add_argument("--module")
    c.add_argument("--json", action="store_true",
                   help="emit the verdict(s) as JSON")
    c.add_argument("--sarif", action="store_true",
                   help="emit SARIF 2.1.0 for GitHub code scanning")
    c.set_defaults(func=_cmd_check)

    f = sub.add_parser("fixtures", help="list the bundled fixtures and where they live")
    f.set_defaults(func=_cmd_fixtures)

    sb = sub.add_parser("submit", help="build a leaderboard submission from verdicts")
    sb.add_argument("--tool", required=True, help="your tool's name")
    sb.add_argument("--tool-version", required=True, help="your tool's version")
    sb.add_argument("--verdicts", help="JSON file of fixture -> verdict (default: the reference checker)")
    sb.add_argument("--url", help="project URL, shown on the board")
    sb.add_argument("--method", help="one line on how your tool decides")
    sb.add_argument("--notes")
    sb.add_argument("-o", "--output")
    sb.set_defaults(func=_cmd_submit)

    va = sub.add_parser("validate", help="check a submission is complete and well formed")
    va.add_argument("submission")
    va.set_defaults(func=_cmd_validate)

    ex = sub.add_parser("export", help="export the corpus as a Hugging Face dataset")
    ex.add_argument("out", nargs="?", default="hf-dataset")
    ex.set_defaults(func=_cmd_export)

    lb = sub.add_parser("leaderboard", help="rank a directory of submissions")
    lb.add_argument("path", nargs="?", default="submissions")
    lb.add_argument("--json", action="store_true")
    lb.set_defaults(func=_cmd_leaderboard)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
