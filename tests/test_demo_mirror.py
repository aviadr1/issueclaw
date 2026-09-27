"""Tests for the README terminal demo (docs/demo.tape + docs/demo_mirror.py)."""

import importlib.util
import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from issueclaw.main import cli

DEMO_SCRIPT = Path(__file__).resolve().parents[1] / "docs" / "demo_mirror.py"
ENG_31 = "linear/teams/ENG/issues/ENG-31-retry-failed-webhook-deliveries.md"


def _load_demo_mirror():
    spec = importlib.util.spec_from_file_location("demo_mirror", DEMO_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=dev",
            "-c",
            "user.email=dev@example.com",
            "-c",
            "init.defaultBranch=main",
            *args,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_demo_flow_produces_the_output_the_gif_shows(tmp_path):
    """INVARIANT: The demo's fixture mirror is a valid issueclaw repo, and
    editing an issue's status then committing yields exactly that field change
    in `issueclaw diff`, as recorded in docs/demo.gif."""
    written = _load_demo_mirror().mirror(tmp_path)
    assert ENG_31 in written

    runner = CliRunner()
    status = runner.invoke(cli, ["--json", "status", "--repo-dir", str(tmp_path)])
    assert status.exit_code == 0, status.output
    assert json.loads(status.output)["issues"] == 3
    assert json.loads(status.output)["teams"] == ["ENG"]

    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "issueclaw pull")
    issue = tmp_path / ENG_31
    issue.write_text(
        issue.read_text().replace("status: Todo\n", "status: In Progress\n")
    )
    _git(tmp_path, "commit", "-qam", "Start ENG-31")

    diff = runner.invoke(cli, ["--json", "diff", "--repo-dir", str(tmp_path)])
    assert diff.exit_code == 0, diff.output
    changes = json.loads(diff.output)
    assert [c["path"] for c in changes] == [ENG_31]
    assert changes[0]["frontmatter_changes"] == {
        "status": {"old": "Todo", "new": "In Progress"}
    }
    assert changes[0]["body_changed"] is False
