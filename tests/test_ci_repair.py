import json
from pathlib import Path
from unittest.mock import patch

from pydantic import BaseModel
import pytest

from issueclaw import ci_repair as repair
from issueclaw.ci_evidence import Job, Step, WorkflowRun
from issueclaw.ci_handoff import parse_link, relocate


class Run(WorkflowRun):
    display_title: str = "nightly both"


class SourceJob(Job):
    id: int


class Policy(BaseModel):
    events: list[str] = ["schedule", "workflow_dispatch"]
    repositories: dict = {"example/backend": {}}


def source(**changes):
    return Run(
        id=12,
        workflow_id=8,
        name="Nightly",
        path=".github/workflows/test.yml",
        head_sha="a" * 40,
        head_branch="main",
        event="schedule",
        status="completed",
        conclusion="failure",
        created_at="2026-10-22T02:00:00Z",
        run_attempt=1,
        html_url="https://github.com/example/backend/actions/runs/12",
    ).model_copy(update=changes)


def job(name="tests", conclusion="failure"):
    return SourceJob(
        id=101,
        name=name,
        status="completed",
        conclusion=conclusion,
        html_url="https://github.com/example/backend/actions/runs/12/job/101",
        steps=[Step(name="test", status="completed", conclusion=conclusion)],
    )


def incident():
    return {
        "id": "a" * 20,
        "repository": "example/backend",
        "base_sha": "a" * 40,
        "base_branch": "main",
        "source": source().model_dump(),
        "jobs": [job().model_dump()],
        "session_run": "https://github.com/example/control/actions/runs/42",
    }


def test_repeated_failure_groups_but_suite_or_lane_changes_do_not():
    jobs = [job().model_dump()]
    original = repair.incident_key("example/backend", source().model_dump(), jobs)
    assert original == repair.incident_key(
        "example/backend", source(id=13).model_dump(), jobs
    )
    assert original != repair.incident_key(
        "example/backend", source(display_title="harness both").model_dump(), jobs
    )
    assert original != repair.incident_key(
        "example/backend", source().model_dump(), [job("android").model_dump()]
    )


def test_discovery_uses_history_and_rejects_feature_branches():
    state = {"incidents": {}, "batches": []}
    runs = [source().model_dump(), source(id=13, head_branch="feature").model_dump()]

    def api(path, *args):
        return (
            {"default_branch": "main"}
            if path == "repos/example/backend"
            else {"sha": "b" * 40}
        )

    def pages(path, field):
        return [job().model_dump()] if field == "jobs" else runs

    with (
        patch.object(repair, "api", side_effect=api),
        patch.object(repair, "pages", side_effect=pages),
    ):
        first = repair.discover(Policy().model_dump(), state, "https://example.com/run")
        second = repair.discover(
            Policy().model_dump(), state, "https://example.com/other"
        )
    assert len(first["assignments"]) == 1
    assert (
        first["assignments"][0]["source"]["head_sha"]
        != first["assignments"][0]["base_sha"]
    )
    assert not second["assignments"]
    assert second["incidents"]  # Peer assignment survives across batches.


def test_discovery_access_failure_is_reported_not_all_green():
    with patch.object(repair, "api", side_effect=ValueError("access denied")):
        batch = repair.discover(Policy().model_dump(), {"incidents": {}}, "url", True)
    assert batch["errors"][0]["repository"] == "example/backend"


def bundle(root, item, **manifest_changes):
    manifest = {
        "repository": item["repository"],
        "sha": item["base_sha"],
        "incident_id": item["id"],
        "session_id": "session",
        **manifest_changes,
    }
    (root / "manifest.json").write_text(json.dumps(manifest))


def test_publisher_rejects_cross_repository_patch(tmp_path):
    item = incident()
    bundle(tmp_path, item, repository="example/other")
    with pytest.raises(ValueError, match="match assignment"):
        repair.publish(tmp_path, tmp_path, {"assignments": [item]})


def test_dependency_defers_without_publishing_or_claiming_pass(tmp_path):
    item, peer = incident(), {**incident(), "id": "b" * 20}
    bundle(tmp_path, item)
    (tmp_path / "diagnosis.json").write_text(
        json.dumps({"depends_on": peer["id"], "summary": "upstream service failed"})
    )
    (tmp_path / "candidate.patch").write_text("must not be published")
    with patch.object(repair, "api") as api:
        receipt = repair.publish(
            tmp_path, tmp_path, {"assignments": [item], "incidents": [item, peer]}
        )
    assert receipt["status"] == "deferred"
    assert "pr" not in receipt
    api.assert_not_called()


def test_no_patch_is_reported_as_attention(tmp_path):
    item = incident()
    bundle(tmp_path, item)
    receipt = repair.publish(tmp_path, tmp_path, {"assignments": [item]})
    assert receipt["status"] == "needs_attention"
    assert "continue" in receipt["next_action"]


def verification():
    return {
        **incident(),
        "status": "verification_pending",
        "pr": {"number": 8, "branch": "ci-repair/abc"},
        "verification": {
            "head_sha": "b" * 40,
            "workflow": "test.yml",
            "dispatched_at": "2026-10-22T06:00:00+00:00",
        },
    }


@pytest.mark.parametrize(
    "jobs,expected",
    [
        ([job("dispatch", "success")], "verification_pending"),
        ([job("tests", "skipped")], "verification_pending"),
        ([job("tests", "success")], "verified"),
    ],
)
def test_verification_requires_original_jobs_on_candidate(jobs, expected):
    item = verification()
    run = source(
        id=30,
        head_sha="b" * 40,
        head_branch="ci-repair/abc",
        event="workflow_dispatch",
        created_at="2026-10-22T06:01:00Z",
        conclusion="success",
    ).model_dump()
    with (
        patch.object(repair, "api", return_value={"head": {"sha": "b" * 40}}),
        patch.object(
            repair,
            "pages",
            side_effect=lambda path, field: (
                [j.model_dump() for j in jobs] if field == "jobs" else [run]
            ),
        ),
    ):
        receipt = repair.refresh_verification(item)
    assert receipt["status"] == expected


def test_later_pr_commit_invalidates_previous_verification():
    with patch.object(repair, "api", return_value={"head": {"sha": "c" * 40}}):
        assert (
            repair.refresh_verification(verification())["status"]
            == "verification_stale"
        )


def test_handoff_rejects_other_schemes_and_traversal():
    assert parse_link("issueclaw-ci://resume/example/control/42/123") == (
        "resume",
        "example/control",
        "42",
        "123",
    )
    for value in [
        "https://example.com",
        "issueclaw-ci://resume/example/control/../../etc",
        "issueclaw-ci://resume/example/control/42/0",
    ]:
        with pytest.raises(ValueError):
            parse_link(value)


def test_relocation_drops_unattended_permission_mode():
    row = json.loads(
        relocate(
            [
                {
                    "type": "user",
                    "cwd": "/runner",
                    "permissionMode": "bypassPermissions",
                    "message": {"content": "original"},
                }
            ],
            Path("local"),
        )
    )
    assert row["permissionMode"] == "default"
    assert row["message"]["content"] == "original"


def test_worker_has_subscription_only_and_no_spend_cap():
    workflow = Path(".github/workflows/ci-repair-worker.yml").read_text()
    assert "claude_code_oauth_token:" in workflow
    assert "anthropic_api_key:" not in workflow
    assert "secrets.ANTHROPIC_API_KEY" not in workflow
    assert "--max-budget-usd" not in workflow
    assert "python-version: '3.12'" not in workflow
