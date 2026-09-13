"""Execute the shipped readiness gate before any checkout or installation."""

import os
from pathlib import Path
import subprocess

import pytest
import yaml


@pytest.mark.parametrize(
    "override,accepted",
    [
        ({}, True),
        ({"LINEAR_API_KEY": ""}, False),
        ({"INBOX_TOKEN": ""}, False),
        ({"INBOX_TOKEN": "   "}, False),
        ({"INBOX_URL": ""}, False),
        ({"INBOX_URL": "http://inbox.example"}, False),
        ({"INBOX_URL": "https://"}, False),
        ({"INBOX_URL": "https://inbox.example?token=secret"}, False),
        ({"INBOX_URL": "https://user:pass@inbox.example"}, False),
        ({"ISSUECLAW_REF": "main"}, False),
    ],
)
def test_readiness_gate_runs_before_expensive_steps(tmp_path, override, accepted):
    workflow = yaml.safe_load(
        (Path(__file__).parents[1] / ".github/workflows/inbox.yml").read_text()
    )
    first = workflow["jobs"]["replay"]["steps"][0]
    assert "run" in first, "Configuration must be validated before checkout"
    env = {
        **os.environ,
        "LINEAR_API_KEY": "test-linear-secret",
        "INBOX_TOKEN": "test-inbox-secret",
        "INBOX_URL": "https://inbox.example",
        "ISSUECLAW_REF": "a" * 40,
        **override,
    }
    assert set(first["env"]) == {
        "LINEAR_API_KEY",
        "INBOX_TOKEN",
        "INBOX_URL",
        "ISSUECLAW_REF",
    }
    result = subprocess.run(
        ["bash", "-e", "-c", first["run"]],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert (result.returncode == 0) == accepted
    assert "test-linear-secret" not in result.stdout + result.stderr
    assert "test-inbox-secret" not in result.stdout + result.stderr
    assert list(tmp_path.iterdir()) == []
