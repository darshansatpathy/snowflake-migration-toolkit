from __future__ import annotations

import json
from pathlib import Path

import pytest

from sfmigrate.assess import assess, write_translations
from sfmigrate.cli import main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "legacy"


def test_assessment_of_the_examples(tmp_path: Path) -> None:
    a = assess(EXAMPLES)
    status = a.by_status()
    assert len(a.files) == 8 and a.statements == sum(status.values())
    assert status["manual"] == 2 and status["auto"] > 10
    assert 0.85 < a.automation_rate() < 1
    assert a.effort_hours() > 0
    md = a.markdown()
    assert "Needs a person" in md and "refresh_summary.sql:1" in md and "close_orders.sql:1" in md
    rows = a.csv().splitlines()
    assert rows[0].startswith("file,line") and len(rows) == a.statements + 1
    written = write_translations(a, tmp_path)
    assert len(written) == 8 and (tmp_path / "assessment.json").exists()
    assert "USE SCHEMA sales;" in (tmp_path / "teradata" / "bteq" / "daily_load.snowflake.sql").read_text()
    single = assess(EXAMPLES / "oracle" / "ddl" / "schema.sql")
    assert single.files[0].path == "schema.sql"
    assert assess(tmp_path / "missing").statements == 0


def test_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    assert main(["sql", "--dialect", "oracle", "SELECT NVL(a, 0) FROM t WHERE ROWNUM <= 5"]) == 0
    out = capsys.readouterr().out
    assert "COALESCE(a, 0)" in out and "LIMIT 5" in out
    assert main(["sql", "--dialect", "teradata", "--json", "REPLACE MACRO m AS (SEL 1;)"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "manual"
    assert main(["sql", "--dialect", "teradata", "--pretty", "REPLACE MACRO m AS (SEL 1;)"]) == 2
    capsys.readouterr()
    assert main(["rules"]) == 0
    assert "OR004" in capsys.readouterr().out
    report = tmp_path / "a"
    assert (
        main(
            [
                "assess",
                str(EXAMPLES),
                "--json",
                f"{report}.json",
                "--csv",
                f"{report}.csv",
                "--markdown",
                f"{report}.md",
            ]
        )
        == 0
    )
    assert json.loads(Path(f"{report}.json").read_text())["files"] == 8
    capsys.readouterr()
    assert main(["translate", str(EXAMPLES), "--out", str(tmp_path / "out")]) == 0
    assert "wrote 8 file(s)" in capsys.readouterr().out
    monkeypatch.delenv("SFM_SOURCE_DSN", raising=False)
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert main(["eval", "--check", "--report", str(tmp_path / "e.md")]) == 0
    assert "53 / 53" in summary.read_text() and "skipped" in summary.read_text()
    assert main(["eval", "--check", "--require-validation"]) == 1
