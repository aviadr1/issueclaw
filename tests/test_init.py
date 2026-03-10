"""Tests for the init command."""

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

from click.testing import CliRunner

from issueclaw.commands import init as init_mod
from issueclaw.main import cli


def test_init_copies_workflow_files(tmp_path):
    """INVARIANT: Init creates .github/workflows/ with both workflow files."""
    runner = CliRunner()
    with patch.dict(os.environ, {"LINEAR_API_KEY": "lin_api_test123"}):
        with patch.object(init_mod, "_run_gh_secret_set", return_value=True):
            with patch.object(init_mod, "_run_initial_pull"):
                result = runner.invoke(cli, ["init", "--repo-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    wf_dir = tmp_path / ".github" / "workflows"
    assert (wf_dir / "issueclaw-webhook.yaml").exists()
    assert (wf_dir / "issueclaw-push.yaml").exists()


def test_init_saves_api_key_to_env_file(tmp_path):
    """INVARIANT: Init saves LINEAR_API_KEY to .env and adds .env to .gitignore."""
    runner = CliRunner()
    with patch.dict(os.environ, {"LINEAR_API_KEY": "lin_api_test123"}, clear=False):
        with patch.object(init_mod, "_run_gh_secret_set", return_value=True):
            with patch.object(init_mod, "_run_initial_pull"):
                result = runner.invoke(cli, ["init", "--repo-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output

    env_file = tmp_path / ".env"
    assert env_file.exists()
    assert "LINEAR_API_KEY=lin_api_test123" in env_file.read_text()

    gitignore = tmp_path / ".gitignore"
    assert gitignore.exists()
    assert ".env" in gitignore.read_text()


def test_init_reads_api_key_from_dotenv(tmp_path):
    """INVARIANT: Init reads LINEAR_API_KEY from .env when not in environment."""
    (tmp_path / ".env").write_text("LINEAR_API_KEY=lin_from_dotenv\n")

    env_without_key = {k: v for k, v in os.environ.items() if k != "LINEAR_API_KEY"}
    runner = CliRunner()
    with patch.dict(os.environ, env_without_key, clear=True):
        with patch.object(init_mod, "_run_gh_secret_set", return_value=True) as mock_gh:
            with patch.object(init_mod, "_run_initial_pull"):
                result = runner.invoke(cli, ["init", "--repo-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    mock_gh.assert_called_once_with("lin_from_dotenv")


def test_init_prompts_for_api_key_when_missing(tmp_path):
    """INVARIANT: Init prompts user for API key when not in env or .env file."""
    env_without_key = {k: v for k, v in os.environ.items() if k != "LINEAR_API_KEY"}
    runner = CliRunner()
    with patch.dict(os.environ, env_without_key, clear=True):
        with patch.object(init_mod, "_run_gh_secret_set", return_value=True) as mock_gh:
            with patch.object(init_mod, "_run_initial_pull"):
                result = runner.invoke(
                    cli,
                    ["init", "--repo-dir", str(tmp_path)],
                    input="lin_prompted_key\n",
                )

    assert result.exit_code == 0, result.output
    mock_gh.assert_called_once_with("lin_prompted_key")
    assert "LINEAR_API_KEY=lin_prompted_key" in (tmp_path / ".env").read_text()


def test_init_reports_gh_unavailable(tmp_path):
    """INVARIANT: Init prints fallback message when gh CLI is not available."""
    runner = CliRunner()
    with patch.dict(os.environ, {"LINEAR_API_KEY": "lin_api_test123"}):
        with patch.object(init_mod, "_run_gh_secret_set", return_value=False):
            with patch.object(init_mod, "_run_initial_pull"):
                result = runner.invoke(cli, ["init", "--repo-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "set it manually" in result.output.lower() or "not available" in result.output.lower()


def test_init_does_not_duplicate_env_entries(tmp_path):
    """INVARIANT: Init does not add duplicate LINEAR_API_KEY to existing .env."""
    (tmp_path / ".env").write_text("LINEAR_API_KEY=existing_key\nOTHER=value\n")

    runner = CliRunner()
    with patch.dict(os.environ, {"LINEAR_API_KEY": "lin_api_test123"}):
        with patch.object(init_mod, "_run_gh_secret_set", return_value=True):
            with patch.object(init_mod, "_run_initial_pull"):
                result = runner.invoke(cli, ["init", "--repo-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    content = (tmp_path / ".env").read_text()
    assert content.count("LINEAR_API_KEY") == 1


def test_init_does_not_duplicate_gitignore_entry(tmp_path):
    """INVARIANT: Init does not add duplicate .env to existing .gitignore."""
    (tmp_path / ".gitignore").write_text(".env\nnode_modules/\n")

    runner = CliRunner()
    with patch.dict(os.environ, {"LINEAR_API_KEY": "lin_api_test123"}):
        with patch.object(init_mod, "_run_gh_secret_set", return_value=True):
            with patch.object(init_mod, "_run_initial_pull"):
                result = runner.invoke(cli, ["init", "--repo-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    content = (tmp_path / ".gitignore").read_text()
    assert content.count(".env") == 1
