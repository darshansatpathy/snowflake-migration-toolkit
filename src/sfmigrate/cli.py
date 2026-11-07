"""The ``sfmigrate`` command line."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from sfmigrate import __version__


def cmd_sql(args: argparse.Namespace) -> int:
    from sfmigrate.translator import translate_statement

    t = translate_statement(args.sql, args.dialect, pretty=args.pretty)
    if args.json:
        print(json.dumps(t.to_dict(), indent=2))
        return 0 if t.status != "manual" else 2
    print(f"-- [{t.status}]")
    for n in t.notes:
        print(f"-- {n.severity}: {n.rule}: {n.message}")
    if t.output:
        print(t.output + ";")
    return 0 if t.status != "manual" else 2


def cmd_assess(args: argparse.Namespace) -> int:
    from sfmigrate.assess import assess

    result = assess(Path(args.path), args.dialect)
    text = result.markdown()
    print(text)
    if args.json:
        Path(args.json).write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    if args.csv:
        Path(args.csv).write_text(result.csv(), encoding="utf-8")
    if args.markdown:
        Path(args.markdown).write_text(text, encoding="utf-8")
    return 0


def cmd_translate(args: argparse.Namespace) -> int:
    from sfmigrate.assess import assess, write_translations

    result = assess(Path(args.path), args.dialect)
    written = write_translations(result, Path(args.out))
    status = result.by_status()
    print(
        f"wrote {len(written)} file(s) to {args.out}: {status['auto']} auto, {status['assisted']} assisted, "
        f"{status['manual']} manual, {status['dropped']} dropped"
    )
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from sfmigrate.validate.compare import Config, run

    report = run(Config.load(Path(args.config)))
    text = report.markdown()
    print(text)
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(report.to_dict(), indent=2, default=str), encoding="utf-8")
    return 0 if report.ok else 1


def cmd_rules(args: argparse.Namespace) -> int:
    import sfmigrate.translator  # noqa: F401 - registers the rule modules
    from sfmigrate.rules import CATALOG

    for rule in CATALOG:
        print(f"{rule.id}  {rule.dialect:<9} {rule.title}: {rule.effect}")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from sfmigrate.evaluation import markdown, run_corpus, run_validation

    corpus = run_corpus()
    dsn = args.source_dsn or os.environ.get("SFM_SOURCE_DSN", "")
    validation = run_validation(dsn, rows=args.rows) if dsn else []
    text = markdown(corpus, validation)
    if not dsn:
        text += "\n(Validation scenarios skipped: set --source-dsn or SFM_SOURCE_DSN to a scratch PostgreSQL database.)\n"
    print(text)
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text)
    ok = corpus.ok and all(r.passed for r in validation)
    if args.check and (not ok or (args.require_validation and not validation)):
        print("evaluation gate failed", file=sys.stderr)
        return 1
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sfmigrate", description="Teradata and Oracle to Snowflake: assess, translate, validate.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("sql", help="translate one statement")
    s.add_argument("sql")
    s.add_argument("--dialect", required=True, choices=["teradata", "oracle"])
    s.add_argument("--pretty", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_sql)

    s = sub.add_parser("assess", help="inventory a codebase: what translates, what needs a person, effort")
    s.add_argument("path")
    s.add_argument("--dialect", choices=["teradata", "oracle"], help="when folders and suffixes don't say")
    s.add_argument("--json")
    s.add_argument("--csv")
    s.add_argument("--markdown")
    s.set_defaults(fn=cmd_assess)

    s = sub.add_parser("translate", help="translate a codebase into Snowflake scripts with review notes")
    s.add_argument("path")
    s.add_argument("--out", required=True)
    s.add_argument("--dialect", choices=["teradata", "oracle"])
    s.set_defaults(fn=cmd_translate)

    s = sub.add_parser("validate", help="compare tables between source and target, row by row")
    s.add_argument("config")
    s.add_argument("--report")
    s.add_argument("--json")
    s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("rules", help="list the translation rules")
    s.set_defaults(fn=cmd_rules)

    s = sub.add_parser("eval", help="the corpus, and the validator against injected defects")
    s.add_argument("--source-dsn", help="scratch PostgreSQL database for the validation scenarios")
    s.add_argument("--rows", type=int, default=20_000)
    s.add_argument("--report")
    s.add_argument("--check", action="store_true")
    s.add_argument("--require-validation", action="store_true", help="with --check, fail if validation was skipped")
    s.set_defaults(fn=cmd_eval)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
