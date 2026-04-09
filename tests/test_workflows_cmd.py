"""Tests for `issueclaw workflows` commands."""

import importlib.resources
import json

from click.testing import CliRunner

from issueclaw.main import cli


def _workflow_dir(repo_dir):
    return repo_dir / ".github" / "workflows"


def test_workflows_upgrade_writes_all_managed_files(tmp_path):
    """INVARIANT: `workflows upgrade` installs push/webhook/sync stubs."""
    runner = CliRunner()
    result = runner.invoke(cli, ["workflows", "upgrade", "--repo-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    wf_dir = _workflow_dir(tmp_path)
    assert (wf_dir / "issueclaw-push.yaml").exists()
    assert (wf_dir / "issueclaw-webhook.yaml").exists()
    assert (wf_dir / "issueclaw-sync.yaml").exists()


def test_workflows_upgrade_overwrites_drifted_managed_file(tmp_path):
    """INVARIANT: `workflows upgrade` repairs content drift for managed files."""
    wf_dir = _workflow_dir(tmp_path)
    wf_dir.mkdir(parents=True, exist_ok=True)
    drifted = wf_dir / "issueclaw-push.yaml"
    drifted.write_text("# drifted by hand\nname: drifted\n")

    runner = CliRunner()
    result = runner.invoke(cli, ["workflows", "upgrade", "--repo-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output

    expected = (
        importlib.resources.files("issueclaw") / "workflows" / "issueclaw-push.yaml"
    ).read_text()
    assert drifted.read_text() == expected


def test_workflows_doctor_reports_healthy_after_upgrade(tmp_path):
    """INVARIANT: `workflows doctor` reports healthy when templates are current."""
    runner = CliRunner()
    upgrade = runner.invoke(cli, ["workflows", "upgrade", "--repo-dir", str(tmp_path)])
    assert upgrade.exit_code == 0, upgrade.output

    result = runner.invoke(cli, ["workflows", "doctor", "--repo-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "issueclaw-push.yaml: ok" in result.output
    assert "issueclaw-webhook.yaml: ok" in result.output
    assert "issueclaw-sync.yaml: ok" in result.output
    assert "present and up to date" in result.output


def test_workflows_doctor_strict_fails_on_drift(tmp_path):
    """INVARIANT: `workflows doctor --strict` fails when managed files are drifted."""
    runner = CliRunner()
    upgrade = runner.invoke(cli, ["workflows", "upgrade", "--repo-dir", str(tmp_path)])
    assert upgrade.exit_code == 0, upgrade.output

    drifted = _workflow_dir(tmp_path) / "issueclaw-sync.yaml"
    drifted.write_text("# Installed by: issueclaw init\nname: drifted\n")

    result = runner.invoke(
        cli, ["workflows", "doctor", "--repo-dir", str(tmp_path), "--strict"]
    )
    assert result.exit_code != 0
    assert "issueclaw-sync.yaml: drifted" in result.output
    assert "workflow doctor failed" in result.output.lower()


def test_workflows_doctor_json_output(tmp_path):
    """INVARIANT: `--json workflows doctor` emits structured per-file status."""
    runner = CliRunner()
    result = runner.invoke(
        cli, ["--json", "workflows", "doctor", "--repo-dir", str(tmp_path)]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["healthy"] is False
    assert "issueclaw-push.yaml" in payload["expected"]
    assert any(file["name"] == "issueclaw-push.yaml" for file in payload["files"])
