"""Execute the shipped readiness gate before any checkout or installation."""

import os
from pathlib import Path
import subprocess
import time

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
        "GITHUB_ENV": str(tmp_path / "job-env"),
        **override,
    }
    assert set(first["env"]) == {
        "LINEAR_API_KEY",
        "INBOX_TOKEN",
        "INBOX_URL",
        "ISSUECLAW_REF",
    }
    started = time.time()
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
    if accepted:
        key, value = (tmp_path / "job-env").read_text().strip().split("=")
        assert key == "ISSUECLAW_JOB_DEADLINE"
        assert started + 270 <= float(value) <= time.time() + 270
        assert list(tmp_path.iterdir()) == [tmp_path / "job-env"]
    else:
        assert list(tmp_path.iterdir()) == []


def test_daily_fast_path_does_not_materialize_mirror_without_pending_work():
    workflow = yaml.safe_load(
        (Path(__file__).parents[1] / ".github/workflows/inbox.yml").read_text()
    )
    steps = workflow["jobs"]["replay"]["steps"]
    checkout = next(
        s for s in steps if s.get("uses", "").startswith("actions/checkout@")
    )
    assert checkout["with"]["sparse-checkout"] == ".sync"
    assert "filter" not in checkout["with"]  # filter overrides sparse mode in checkout
    discovery = next(s for s in steps if s.get("id") == "discovery")
    assert discovery["if"] == "inputs.reconcile"
    for step in steps[steps.index(discovery) + 1 :]:
        assert (
            step["if"]
            == "${{ !inputs.reconcile || steps.discovery.outputs.pending == 'true' }}"
        )
