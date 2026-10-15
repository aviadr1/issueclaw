"""Briefings must report executed jobs, not infer coverage from a workflow badge."""

import json
import subprocess
from unittest.mock import patch

import pytest

from issueclaw import ci_evidence as ci


REPO = "org/service"
HEAD = "a" * 40


def run(run_id=1, **changes):
    return ci.WorkflowRun(
        id=run_id,
        workflow_id=10,
        name="Non-default Tests",
        path=".github/workflows/tests.yml",
        head_sha=HEAD,
        head_branch="main",
        event="push",
        status="completed",
        conclusion="success",
        created_at="2026-10-15T00:00:00Z",
        run_attempt=1,
        html_url=f"https://github.com/{REPO}/actions/runs/{run_id}",
    ).model_copy(update=changes)


def job(name, conclusion="success"):
    return ci.Job(
        name=name,
        status="completed",
        conclusion=conclusion,
        html_url=f"https://github.com/{REPO}/actions/runs/1/job/2",
        steps=[],
    )


def collect(runs, jobs, *, changed_head=False, incomplete_jobs=False):
    """Exercise collection through the real JSON transport and paginated API shape."""

    def github(args, **kwargs):
        endpoint = args[-1]
        if "graphql" in args:
            payload = {
                "data": {
                    "repository": {
                        "object": {
                            "entries": [
                                {
                                    "name": "tests.yml",
                                    "object": {
                                        "text": "name: Non-default Tests\non:\n  pull_request: {}\n  workflow_dispatch: {}\n"
                                    },
                                },
                                {
                                    "name": "types.yml",
                                    "object": {
                                        "text": "name: Types\non:\n  push:\n    branches: ['fix/*']\n    paths: ['src/**']\n"
                                    },
                                },
                            ]
                        }
                    }
                }
            }
        elif endpoint == f"repos/{REPO}":
            payload = {"default_branch": "main"}
        elif endpoint == f"repos/{REPO}/commits/main":
            payload = {"sha": "b" * 40 if changed_head else HEAD}
        elif endpoint.endswith("/git/ref/heads/main"):
            payload = {"object": {"sha": HEAD}}
        elif "/jobs?" in endpoint:
            run_id = int(endpoint.split("/runs/")[1].split("/")[0])
            rows = jobs[run_id]
            total = len(rows) + int(incomplete_jobs)
            payload = [
                {"total_count": total, "jobs": [row.model_dump() for row in rows[:1]]},
                {"total_count": total, "jobs": [row.model_dump() for row in rows[1:]]},
            ]
        elif "/actions/runs?" in endpoint:
            payload = [
                {
                    "total_count": len(runs),
                    "workflow_runs": [r.model_dump(exclude={"jobs"}) for r in runs[:1]],
                },
                {
                    "total_count": len(runs),
                    "workflow_runs": [r.model_dump(exclude={"jobs"}) for r in runs[1:]],
                },
            ]
        else:
            raise AssertionError(args)
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload))

    with patch.object(subprocess, "run", side_effect=github):
        return ci.collect_default_branch_ci(REPO)


def test_success_badge_preserves_skipped_workload_and_trigger_policy():
    evidence = collect(
        [run()], {1: [job("Resolve trigger"), job("Scan inventory", "skipped")]}
    )
    result = evidence.latest_head_runs[0]
    assert result.conclusion == "success"
    assert [(j.name, j.conclusion) for j in result.jobs] == [
        ("Resolve trigger", "success"),
        ("Scan inventory", "skipped"),
    ]
    policies = evidence.workflow_policies
    assert policies[0].events == ["pull_request", "workflow_dispatch"]
    assert policies[1].push == {"branches": ["fix/*"], "paths": ["src/**"]}
    assert policies[0].source_url.endswith(f"/{HEAD}/.github/workflows/tests.yml")


def test_unrelated_manual_success_never_erases_failed_push_or_its_failed_step():
    failed = job("sports / smoke", "failure")
    failed.steps = [
        ci.Step(name="Run pytest", status="completed", conclusion="failure")
    ]
    evidence = collect(
        [run(conclusion="failure"), run(2, event="workflow_dispatch")],
        {1: [failed], 2: [job("idk / manual")]},
    )
    assert len(evidence.latest_head_runs) == 2
    assert evidence.latest_head_runs[0].jobs[0].steps[0].name == "Run pytest"
    assert evidence.latest_head_runs[0].conclusion == "failure"
    assert evidence.latest_head_runs[1].event == "workflow_dispatch"


def test_skipped_comment_runs_are_auditable_without_drowning_the_report():
    evidence = collect(
        [run(), run(2, event="issue_comment", conclusion="skipped")],
        {1: [job("Tests")]},
    )
    assert [r.id for r in evidence.latest_head_runs] == [1]
    assert [r.id for r in evidence.skipped_runs] == [2]


@pytest.mark.parametrize("condition", ["changed_head", "incomplete_jobs"])
def test_incomplete_or_mixed_revision_evidence_blocks_publication(condition):
    with pytest.raises(RuntimeError):
        collect([run()], {1: [job("Tests")]}, **{condition: True})


def test_run_from_another_head_cannot_be_attributed_to_default_branch():
    with pytest.raises(RuntimeError, match="head"):
        collect([run(head_sha="b" * 40)], {1: [job("Tests")]})
