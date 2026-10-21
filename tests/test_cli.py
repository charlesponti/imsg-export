"""CLI surface: commands, exit codes, and the `all` pipeline."""

from __future__ import annotations

import subprocess
import sys

import pytest

from imsg_export import __version__
from imsg_export.cli import main


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_command_prints_help(capsys):
    assert main([]) == 2
    assert "export" in capsys.readouterr().out


def test_module_entry_point_runs():
    result = subprocess.run(
        [sys.executable, "-m", "imsg_export", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "imsg-export" in result.stdout


def test_export_command(tmp_path, fake_db, capsys):
    code = main(["export", str(tmp_path / "out"), "--db", str(fake_db), "--no-contacts"])
    assert code == 0
    assert "exported 7 messages" in capsys.readouterr().out


def test_verify_command_exit_codes(tmp_path, fake_db, capsys):
    target = tmp_path / "out"
    main(["export", str(target), "--db", str(fake_db), "--no-contacts"])
    capsys.readouterr()
    assert main(["verify", str(target), "--db", str(fake_db)]) == 0
    assert "VERDICT: complete" in capsys.readouterr().out

    (target / "messages.jsonl").write_text("", encoding="utf-8")
    assert main(["verify", str(target), "--db", str(fake_db)]) == 1
    assert "VERDICT: INCOMPLETE" in capsys.readouterr().out


def test_missing_database_exits_cleanly(tmp_path, capsys):
    code = main(["export", str(tmp_path / "out"), "--db", str(tmp_path / "nope.db")])
    assert code == 1
    assert "no Messages database" in capsys.readouterr().err


def test_all_pipeline_writes_audit_and_readme(tmp_path, fake_db):
    target = tmp_path / "out"
    code = main(["all", str(target), "--db", str(fake_db), "--no-contacts"])
    assert code == 0
    assert (target / "README.md").exists()
    audit = (target / "audit.txt").read_text(encoding="utf-8")
    assert "VERDICT: complete" in audit
    readme = (target / "README.md").read_text(encoding="utf-8")
    assert "7 message rows" in readme
    assert "Completeness check" in readme
