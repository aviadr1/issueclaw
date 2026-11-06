"""Scheduled CI repair receipts, discovery and trusted publication.

The model proposes a patch. This module owns GitHub writes and verification.
No LLM result can set the verified state. Authentication is supplied per step.
"""

import argparse
import base64
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import uuid

from issueclaw import report_evidence as report
from issueclaw.briefing_trace import model_trace, write_json


FAILURES = {"failure", "timed_out", "cancelled", "action_required", "startup_failure"}
STATE_BRANCH = "ci-repair-state"


def api(path, method="GET", body=None):
    args = ["api", path, "--method", method]
    if body is None:
        return report.gh_json(*args)
    proc = subprocess.run(
        ["gh", *args, "--input", "-"],
        input=json.dumps(body),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def pages(path, field):
    rows = report.gh_json("api", "--paginate", "--slurp", path)
    return [item for page in rows for item in (page[field] if field else page)]


def now():
    return datetime.now(timezone.utc).isoformat()


def output(key, value):
    if os.environ.get("GITHUB_OUTPUT"):
        # Delimited outputs support multi-line prompts without shell interpolation.
        delimiter = uuid.uuid4().hex
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            stream.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")


def read_state(repository):
    # A missing branch is the only empty-state condition. Auth/network errors fail.
    branches = pages(f"repos/{repository}/branches?per_page=100", None)
    if not any(b["name"] == STATE_BRANCH for b in branches):
        return {"version": 1, "incidents": {}, "batches": []}, None
    item = api(f"repos/{repository}/contents/receipts.json?ref={STATE_BRANCH}")
    return json.loads(base64.b64decode(item["content"])), item["sha"]


def save_state(repository, state, sha):
    if sha is None:
        # Seed an orphan data branch; never copy the company's source tree.
        tree = api(
            f"repos/{repository}/git/trees",
            "POST",
            {
                "tree": [
                    {
                        "path": "receipts.json",
                        "mode": "100644",
                        "type": "blob",
                        "content": json.dumps(state, indent=2) + "\n",
                    }
                ]
            },
        )
        commit = api(
            f"repos/{repository}/git/commits",
            "POST",
            {
                "message": "Initialize CI repair receipts",
                "tree": tree["sha"],
                "parents": [],
            },
        )
        api(
            f"repos/{repository}/git/refs",
            "POST",
            {
                "ref": f"refs/heads/{STATE_BRANCH}",
                "sha": commit["sha"],
            },
        )
    else:
        api(
            f"repos/{repository}/contents/receipts.json",
            "PUT",
            {
                "branch": STATE_BRANCH,
                "sha": sha,
                "message": "Record CI repair attempts",
                "content": base64.b64encode(
                    (json.dumps(state, indent=2) + "\n").encode()
                ).decode(),
            },
        )


def incident_key(repository, run, jobs):
    # Different named suites (e.g. smoke/harness) and matrix failures stay distinct.
    # This groups repeat occurrences, not a claim that their root causes are equal.
    value = [
        repository,
        run["path"],
        run.get("head_branch"),
        run.get("display_title", run["name"]),
        sorted(j["name"] for j in jobs if j.get("conclusion") in FAILURES),
    ]
    return hashlib.sha256(json.dumps(value).encode()).hexdigest()[:20]


def run_history(repository, branches, days):
    found = {}
    end = datetime.now(timezone.utc)
    for _ in range(days):
        start = end - timedelta(days=1)
        window = quote(
            start.strftime("%Y-%m-%dT%H:%M:%SZ")
            + ".."
            + end.strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        for branch in branches:
            rows = pages(
                f"repos/{repository}/actions/runs?branch={quote(branch, safe='')}&created={window}&per_page=100",
                "workflow_runs",
            )
            if len(rows) >= 1000:
                raise ValueError(f"Run search truncated for {branch} in {window}")
            found.update({row["id"]: row for row in rows})
        end = start
    return sorted(found.values(), key=lambda r: r["created_at"], reverse=True)


def discover(config, state, run_url, dry_run=False):
    cohort, errors, observed = [], [], []
    for repository in config["repositories"]:
        try:
            metadata = api(f"repos/{repository}")
            branch = metadata["default_branch"]
            head = api(f"repos/{repository}/commits/{quote(branch, safe='')}")["sha"]
            policy = config["repositories"][repository]
            policy_path = policy.get("policy_path")
            if policy_path:
                policy_ref = policy.get("preview_policy_ref", head) if dry_run else head
                source = api(
                    f"repos/{repository}/contents/{policy_path}?ref={policy_ref}"
                )
                policy = json.loads(base64.b64decode(source["content"]))
            runs = run_history(
                repository,
                policy.get("branches", [branch]),
                config.get("lookback_days", 7),
            )
            seen = set()
            for run in runs:
                if run.get("head_branch") not in policy.get(
                    "branches", [branch]
                ) or run.get("event") not in policy.get("events", config["events"]):
                    continue
                if run["path"] in policy.get("exclude_workflows", []):
                    continue
                if run.get("conclusion") not in FAILURES or "ci-repair" in run["path"]:
                    continue
                jobs = pages(
                    f"repos/{repository}/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100",
                    "jobs",
                )
                key = incident_key(repository, run, jobs)
                if key in seen:
                    continue
                seen.add(key)
                old = state["incidents"].get(key, {})
                target_branch = run["head_branch"]
                target_head = (
                    head
                    if target_branch == branch
                    else api(
                        f"repos/{repository}/commits/{quote(target_branch, safe='')}"
                    )["sha"]
                )
                # Keep unresolved incidents across moving default heads and scan windows.
                # Repeated discovery of the same attempt never launches duplicate work.
                source = f"{run['id']}:{run['run_attempt']}"
                item = {
                    **old,
                    "id": key,
                    "repository": repository,
                    "source": run,
                    "jobs": jobs,
                    "source_attempt": source,
                    "base_branch": target_branch,
                    "base_sha": target_head,
                    "policy": policy,
                    "policy_sha": head,
                    "observed_at": now(),
                    "owner": key,
                    "publication_access": metadata.get("permissions", {}).get("push"),
                    "later_runs": [
                        r
                        for r in runs
                        if r["path"] == run["path"]
                        and r["created_at"] > run["created_at"]
                        and r.get("head_branch") == target_branch
                    ][:20],
                }
                if old.get("source_attempt") != source:
                    item["status"] = "discovered"
                if old.get("pr"):
                    pr = api(f"repos/{repository}/pulls/{old['pr']['number']}")
                    if pr["state"] == "open":
                        item["status"] = "existing_draft"
                        item["pr"]["head_sha"] = pr["head"]["sha"]
                        item["next_action"] = (
                            "Review or continue the existing PR; no duplicate repair."
                        )
                if item.get("status", "discovered") == "discovered":
                    item.update(
                        status="queued" if dry_run else "assigned",
                        session_run=run_url,
                        assigned_at=now(),
                        attempt_id=str(os.environ.get("GITHUB_RUN_ID", "preview")),
                    )
                    cohort.append(item)
                state["incidents"][key] = item
                observed.append(item)
        except (subprocess.CalledProcessError, ValueError, KeyError) as error:
            errors.append({"repository": repository, "error": str(error)[:600]})
    # All incidents remain visible to every worker, including existing owners.
    return {
        "version": 1,
        "created_at": now(),
        "run_url": run_url,
        "errors": errors,
        "assignments": cohort,
        "incidents": list(state["incidents"].values()),
    }


def prepare(batch, key, root, checkout):
    assignment = next(i for i in batch["assignments"] if i["id"] == key)
    root.mkdir(parents=True, exist_ok=True)
    session = str(uuid.uuid4())
    manifest = {
        "version": 1,
        "kind": "ci-repair",
        "session_id": session,
        "repository": assignment["repository"],
        "sha": assignment["base_sha"],
        "coordinator_repository": os.environ["GITHUB_REPOSITORY"],
        "run_id": os.environ["GITHUB_RUN_ID"],
        "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "incident_id": key,
        "session_run": batch["run_url"],
        "created_at": now(),
        "authentication": "claude_subscription_oauth",
        "cloud_url": None,
    }
    write_json(root / "manifest.json", manifest)
    write_json(root / "assignment.json", assignment)
    write_json(root / "cohort.json", batch)
    # Logs are evidence, not instructions. No cross-repository write token survives this step.
    for job in assignment["jobs"]:
        if job.get("conclusion") not in FAILURES:
            continue
        proc = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{assignment['repository']}/actions/jobs/{job['id']}/logs",
            ],
            capture_output=True,
            check=False,
        )
        (root / f"job-{job['id']}.log").write_bytes(proc.stdout[-2_000_000:])
    prompt = (Path(__file__).parent / "prompts/ci-repair.md").read_text(
        encoding="utf-8"
    )
    prompt = (
        prompt.replace("{{EVIDENCE}}", str(root))
        .replace("{{CHECKOUT}}", str(checkout))
        .replace("{{INCIDENT}}", key)
    )
    model_trace(root, "repair", prompt, "claude-sonnet-5-5", "claude-opus-5-5", "haiku")
    settings = {
        "hooks": {
            name: [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"node {Path(__file__).with_name('ci-repair-checkpoint.mjs')} hook",
                            "timeout": 30,
                        }
                    ]
                }
            ]
            for name in [
                "UserPromptSubmit",
                "PreToolUse",
                "PostToolUse",
                "Stop",
                "SessionEnd",
            ]
        }
    }
    write_json(root / "settings.json", settings)
    output("session", session)
    output("settings", root / "settings.json")
    output("prompt", prompt)
    output(
        "metadata",
        json.dumps(
            {
                "incident_id": key,
                "repository": assignment["repository"],
                "source_run": assignment["source"]["html_url"],
                "repair_run": batch["run_url"],
                "authentication": "subscription",
            }
        ),
    )


def git(checkout, *args):
    return subprocess.check_output(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(checkout), *args], text=True
    ).strip()


def capture(root, checkout):
    manifest = json.loads((root / "manifest.json").read_text())
    # Stage only to construct an artifact. Never commit/push with model credentials.
    subprocess.run(["git", "-C", str(checkout), "add", "-A"], check=True)
    patch = subprocess.check_output(
        ["git", "-C", str(checkout), "diff", "--cached", "--binary", manifest["sha"]]
    )
    (root / "candidate.patch").write_bytes(patch)
    execution = Path(os.environ["RUNNER_TEMP"]) / "claude-execution-output.json"
    result = {}
    if execution.exists():
        records = json.loads(execution.read_text())
        result = next((r for r in reversed(records) if r.get("type") == "result"), {})
    write_json(
        root / "usage.json",
        {
            "authentication": "subscription",
            "usage": result.get("usage"),
            "model_usage": result.get("modelUsage"),
            "estimated_api_equivalent_usd": result.get("total_cost_usd"),
            "note": "API-equivalent estimate, not a subscription invoice. Missing means unavailable, not zero.",
            "action_outcome": os.environ.get("ACTION_OUTCOME", "unknown"),
        },
    )


def traces(root):
    manifest = json.loads((root / "manifest.json").read_text())
    headers = {
        "x-api-key": os.environ["LANGSMITH_API_KEY"],
        "Content-Type": "application/json",
    }
    workspace = os.environ["LANGSMITH_WORKSPACE_ID"]
    headers["x-tenant-id"] = workspace

    def request(path, body=None):
        req = urllib.request.Request(
            "https://api.smith.langchain.com" + path,
            headers=headers,
            data=json.dumps(body).encode() if body is not None else None,
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)

    projects = request("/sessions?name=" + quote(os.environ["CC_LANGSMITH_PROJECT"]))
    project = next(
        p["id"] for p in projects if p["name"] == os.environ["CC_LANGSMITH_PROJECT"]
    )
    runs = []
    for attempt in range(4):
        runs = request(
            "/runs/query",
            {
                "session": [project],
                "limit": 100,
                "filter": f'and(eq(metadata_key, "repair_run"), eq(metadata_value, "{manifest["session_run"]}"))',
            },
        )["runs"]
        runs = [
            r
            for r in runs
            if r.get("extra", {}).get("metadata", {}).get("incident_id")
            == manifest["incident_id"]
        ]
        if runs:
            break
        time.sleep(10)
    links = [
        f"https://smith.langchain.com/o/{workspace}/projects/p/{project}/r/{r['id']}?trace_id={r['trace_id']}"
        for r in runs
        if not r.get("parent_run_id")
    ]
    write_json(
        root / "traces.json",
        {"verified_at": now(), "urls": links, "run_count": len(runs)},
    )
    if not links:
        raise RuntimeError("No remote LangSmith trace confirmed for this exact attempt")


def publish(root, checkout, batch):
    manifest = json.loads((root / "manifest.json").read_text())
    item = next(i for i in batch["assignments"] if i["id"] == manifest["incident_id"])
    # Rebind untrusted worker artifacts to the coordinator's independent assignment.
    if (manifest["repository"], manifest["sha"]) != (
        item["repository"],
        item["base_sha"],
    ):
        raise ValueError("Checkpoint does not match assignment")
    receipt = {
        **item,
        "session_id": manifest["session_id"],
        "status": "needs_attention",
        "usage": json.loads((root / "usage.json").read_text())
        if (root / "usage.json").exists()
        else None,
    }
    receipt["traces"] = (
        json.loads((root / "traces.json").read_text())
        if (root / "traces.json").exists()
        else {"urls": [], "status": "unverified"}
    )
    diagnosis = root / "diagnosis.json"
    proposal = json.loads(diagnosis.read_text()) if diagnosis.exists() else {}
    receipt["diagnosis"] = proposal
    dependency = proposal.get("depends_on")
    if dependency:
        if dependency == item["id"] or dependency not in {
            i["id"] for i in batch["incidents"]
        }:
            receipt["next_action"] = "Invalid dependency; inspect the session."
        else:
            receipt.update(
                status="deferred",
                depends_on=dependency,
                next_action="Upstream owner investigates; this CI remains unverified.",
            )
        return receipt
    patch = root / "candidate.patch"
    if not patch.exists() or patch.stat().st_size == 0:
        receipt["next_action"] = "No patch produced. View or continue the session."
        return receipt
    if patch.stat().st_size > 10_000_000:
        raise ValueError("Patch exceeds 10 MB; manual review required")
    repository = item["repository"]
    branch = "ci-repair/" + item["id"]
    existing = api(
        f"repos/{repository}/pulls?state=open&head={repository.split('/')[0]}:{branch}"
    )
    if existing:
        receipt.update(
            status="existing_draft",
            pr={
                "number": existing[0]["number"],
                "url": existing[0]["html_url"],
                "head_sha": existing[0]["head"]["sha"],
            },
        )
        return receipt
    git(checkout, "checkout", "--detach", item["base_sha"])
    git(checkout, "apply", "--index", str(patch.resolve()))
    paths = git(checkout, "diff", "--cached", "--name-only").splitlines()
    if not paths:
        return receipt
    # Preserve changes for review but never dispatch a workflow the model edited.
    receipt["workflow_changed"] = any(p.startswith(".github/") for p in paths)
    git(checkout, "config", "user.name", "CI repair")
    git(checkout, "config", "user.email", "ci-repair@users.noreply.github.com")
    git(checkout, "checkout", "-b", branch)
    git(checkout, "commit", "-m", f"fix: investigate CI failure {item['id']}")
    # gh credential helper uses only the publisher step's token; no token enters URLs.
    git(
        checkout,
        "-c",
        "credential.helper=",
        "-c",
        "credential.helper=!gh auth git-credential",
        "push",
        "origin",
        branch,
    )
    sha = git(checkout, "rev-parse", "HEAD")
    body = (
        f"Repair proposal for {item['source']['html_url']} (attempt {item['source']['run_attempt']}).\n\n"
        f"Agent session and private checkpoints: {item['session_run']}\n\n"
        f"Incident: `{item['id']}`. Candidate: `{sha}`.\n\n"
        "**Draft; verification pending.** A successful agent run is not proof of a CI fix. "
        "No automated merge or ready-for-review transition.\n\n"
        + str(proposal.get("summary", "Inspect the saved session for diagnosis."))[
            :6000
        ]
    )
    pr = api(
        f"repos/{repository}/pulls",
        "POST",
        {
            "head": branch,
            "base": item["base_branch"],
            "draft": True,
            "title": f"fix(ci): {item['source']['name']}"[:180],
            "body": body,
        },
    )
    receipt.update(
        status="verification_pending",
        pr={
            "number": pr["number"],
            "url": pr["html_url"],
            "head_sha": sha,
            "branch": branch,
        },
    )
    return receipt


def verify(receipt, config):
    if receipt["status"] != "verification_pending":
        return receipt
    policy = receipt["policy"].get("verification", {}).get(receipt["source"]["path"])
    if policy and "cases" in policy:
        matches = [
            case
            for case in policy["cases"]
            if re.fullmatch(
                case["source_title"], receipt["source"].get("display_title", "")
            )
        ]
        policy = matches[0] if len(matches) == 1 else None
    if not policy or receipt.get("workflow_changed"):
        receipt["next_action"] = (
            "Candidate-specific validation requires review; inspect/continue the session."
        )
        return receipt
    repository, pr = receipt["repository"], receipt["pr"]
    workflow = policy["workflow"]
    inputs = {
        k: str(v).replace("{sha}", pr["head_sha"])
        for k, v in policy.get("inputs", {}).items()
    }
    before = now()
    api(
        f"repos/{repository}/actions/workflows/{workflow}/dispatches",
        "POST",
        {"ref": pr["branch"], "inputs": inputs},
    )
    receipt["verification"] = {
        "dispatched_at": before,
        "workflow": workflow,
        "inputs": inputs,
        "head_sha": pr["head_sha"],
        "status": "pending",
    }
    receipt["next_action"] = (
        "Await equivalent candidate CI; briefing will refresh its status."
    )
    return receipt


def refresh_verification(item):
    proof = item.get("verification")
    if not proof:
        return item
    repository, pr = item["repository"], item["pr"]
    current = api(f"repos/{repository}/pulls/{pr['number']}")
    if current["head"]["sha"] != proof["head_sha"]:
        item["status"] = "verification_stale"
        return item
    runs = pages(
        f"repos/{repository}/actions/workflows/{proof['workflow']}/runs?head_sha={proof['head_sha']}&event=workflow_dispatch&per_page=100",
        "workflow_runs",
    )
    candidates = [
        r
        for r in runs
        if r["head_branch"] == pr["branch"]
        and r["created_at"] >= proof["dispatched_at"][:19] + "Z"
    ]
    if len(candidates) != 1:
        item["next_action"] = (
            "Verification run missing or ambiguous; inspect the session and CI."
        )
        return item
    run = candidates[0]
    proof.update(
        run_url=run["html_url"],
        run_id=run["id"],
        run_attempt=run["run_attempt"],
        status=run["status"],
    )
    jobs = pages(
        f"repos/{repository}/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100",
        "jobs",
    )
    required = {j["name"] for j in item["jobs"] if j["conclusion"] != "skipped"}
    passed = {j["name"] for j in jobs if j["conclusion"] == "success"}
    proof["missing_required_jobs"] = sorted(required - passed)
    if run["conclusion"] in FAILURES:
        item["status"] = "verification_failed"
    elif run["conclusion"] == "success" and required and required <= passed:
        item["status"] = "verified"
        item["next_action"] = "Review the draft PR and its equivalent candidate CI."
    else:
        item["status"] = "verification_pending"
    return item


def briefing_snapshot(repository, repos):
    state, _ = read_state(repository)
    selected = []
    for original in state["incidents"].values():
        if original["repository"] not in repos:
            continue
        item = refresh_verification(dict(original))
        attempt = item.get("attempt_id")
        if attempt and attempt.isdecimal():
            run = api(f"repos/{repository}/actions/runs/{attempt}")
            item["agent_run_status"] = run["status"]
            item["agent_run_conclusion"] = run["conclusion"]
            artifacts = pages(
                f"repos/{repository}/actions/runs/{attempt}/artifacts?per_page=100",
                "artifacts",
            )
            candidates = [
                a
                for a in artifacts
                if not a["expired"]
                and a["name"].startswith(f"repair-{item['id']}-")
                and ("-final-" in a["name"] or "-checkpoint-" in a["name"])
            ]
            if candidates:
                artifact = max(candidates, key=lambda a: a["created_at"])
                item["checkpoint"] = {
                    "id": artifact["id"],
                    "created_at": artifact["created_at"],
                    "expires_at": artifact["expires_at"],
                    "url": f"https://github.com/{repository}/actions/runs/{attempt}/artifacts/{artifact['id']}",
                    "local_uri": f"issueclaw-ci://resume/{repository}/{attempt}/{artifact['id']}",
                    "cloud_uri": f"issueclaw-ci://cloud/{repository}/{attempt}/{artifact['id']}",
                }
                if state.get("handoff_base_url"):
                    item["checkpoint"]["handoff_url"] = (
                        f"{state['handoff_base_url']}#{repository}/{attempt}/{artifact['id']}"
                    )
            if item["status"] == "assigned" and run["status"] == "completed":
                item["status"] = "needs_attention"
                item["next_action"] = (
                    "Repair ended without a final receipt; view or continue the latest checkpoint."
                )
        selected.append(item)
    return {
        "snapshot_at": now(),
        "incidents": selected,
        "batches": state["batches"][-7:],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "operation",
        choices=["discover", "prepare", "capture", "traces", "publish", "finalize"],
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--batch", type=Path, default=Path("/tmp/ci-repair-batch.json"))
    parser.add_argument("--root", type=Path, default=Path("/tmp/ci-repair"))
    parser.add_argument("--checkout", type=Path, default=Path("."))
    parser.add_argument("--incident", default=os.environ.get("REPAIR_INCIDENT", ""))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    repository = os.environ["GITHUB_REPOSITORY"]
    run_url = (
        f"https://github.com/{repository}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    )
    if args.operation == "discover":
        config = json.loads(args.config.read_text())
        state, sha = read_state(repository)
        batch = discover(config, state, run_url, args.dry_run)
        write_json(args.batch, batch)
        output(
            "matrix",
            json.dumps(
                {
                    "include": [
                        {
                            "id": i["id"],
                            "repository": i["repository"],
                            "sha": i["base_sha"],
                        }
                        for i in batch["assignments"]
                    ]
                }
            ),
        )
        output("count", len(batch["assignments"]))
        if not args.dry_run:
            state["batches"].append(
                {"url": run_url, "at": now(), "errors": batch["errors"]}
            )
            save_state(repository, state, sha)
    elif args.operation == "prepare":
        prepare(
            json.loads(args.batch.read_text()),
            args.incident,
            args.root,
            args.checkout.resolve(),
        )
    elif args.operation == "capture":
        capture(args.root, args.checkout)
    elif args.operation == "traces":
        traces(args.root)
    elif args.operation == "publish":
        receipt = publish(args.root, args.checkout, json.loads(args.batch.read_text()))
        receipt = verify(receipt, json.loads(args.config.read_text()))
        write_json(args.root / "receipt.json", receipt)
    else:
        state, sha = read_state(repository)
        for path in args.root.rglob("receipt.json"):
            item = json.loads(path.read_text())
            state["incidents"][item["id"]] = item
        for path in args.root.rglob("handoff-site.json"):
            state["handoff_base_url"] = json.loads(path.read_text())["url"]
        save_state(repository, state, sha)


if __name__ == "__main__":
    main()
