"""Read-only CI evidence pinned to one default-branch revision.

A successful workflow is an orchestration result, not proof that its tests or
scans executed. Preserve job outcomes and trigger policy for the report writer.
"""

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

from pydantic import BaseModel, Field
import yaml

from issueclaw import report_evidence as report


class Step(BaseModel):
    name: str
    status: str
    conclusion: str | None


class Job(BaseModel):
    name: str
    status: str
    conclusion: str | None
    html_url: str
    steps: list[Step]


class WorkflowRun(BaseModel):
    id: int
    workflow_id: int
    name: str
    path: str
    head_sha: str
    head_branch: str | None
    event: str
    status: str
    conclusion: str | None
    created_at: str
    run_attempt: int
    html_url: str
    jobs: list[Job] = Field(default_factory=list)


class RunPage(BaseModel):
    total_count: int
    workflow_runs: list[WorkflowRun]


class JobPage(BaseModel):
    total_count: int
    jobs: list[Job]


class WorkflowPolicy(BaseModel):
    name: str
    path: str
    source_url: str
    events: list[str]
    # Trigger filters are GitHub's wire contract, including future filter keys.
    push: dict | None = None


class RepositoryCI(BaseModel):
    repo: str
    default_branch: str
    head_sha: str
    latest_head_runs: list[WorkflowRun]
    skipped_runs: list[WorkflowRun]
    workflow_policies: list[WorkflowPolicy]


def workflow_policies(repo: str, head: str) -> list[WorkflowPolicy]:
    owner, name = repo.split("/")
    data = report.gh_json(
        "api",
        "graphql",
        "-f",
        "owner=" + owner,
        "-f",
        "name=" + name,
        "-f",
        "expression=" + head + ":.github/workflows",
        "-f",
        "query="
        + """query($owner:String!,$name:String!,$expression:String!) {
          repository(owner:$owner,name:$name) { object(expression:$expression) {
            ... on Tree { entries { name object { ... on Blob { text } } } }
          } }
        }""",
    )
    if data.get("errors"):
        raise RuntimeError(f"Incomplete workflow policies for {repo}")
    tree = data["data"]["repository"]["object"]
    policies = []
    for entry in tree["entries"] if tree else []:
        if not entry["name"].endswith((".yml", ".yaml")):
            continue
        definition = yaml.safe_load(entry["object"]["text"])
        # PyYAML's YAML 1.1 loader parses unquoted `on` as True.
        triggers = definition.get("on", definition.get(True, {}))
        if isinstance(triggers, str):
            triggers = {triggers: None}
        elif isinstance(triggers, list):
            triggers = dict.fromkeys(triggers)
        path = ".github/workflows/" + entry["name"]
        policies.append(
            WorkflowPolicy(
                name=definition.get("name", entry["name"]),
                path=path,
                source_url=f"https://github.com/{repo}/blob/{head}/{path}",
                events=sorted(triggers),
                push=triggers.get("push"),
            )
        )
    return policies


def collect_jobs(repo: str, run: WorkflowRun) -> WorkflowRun:
    pages = [
        JobPage.model_validate(page)
        for page in report.gh_json(
            "api",
            "--paginate",
            "--slurp",
            f"repos/{repo}/actions/runs/{run.id}/attempts/{run.run_attempt}/jobs?per_page=100",
        )
    ]
    run.jobs = [job for page in pages for job in page.jobs]
    # Never silently publish a truncated matrix or combine jobs across attempts.
    if not pages or any(page.total_count != len(run.jobs) for page in pages):
        raise RuntimeError(f"Incomplete jobs for {repo} run {run.id}")
    return run


def collect_default_branch_ci(repo: str) -> RepositoryCI:
    branch = report.gh_json("api", f"repos/{repo}")["default_branch"]
    branch_path = quote(branch, safe="")
    head = report.gh_json("api", f"repos/{repo}/git/ref/heads/{branch_path}")["object"][
        "sha"
    ]
    pages = [
        RunPage.model_validate(page)
        for page in report.gh_json(
            "api",
            "--paginate",
            "--slurp",
            f"repos/{repo}/actions/runs?head_sha={head}&per_page=100",
        )
    ]
    runs = [run for page in pages for run in page.workflow_runs]
    if not pages or any(page.total_count != len(runs) for page in pages):
        raise RuntimeError(f"Incomplete default-branch CI for {repo}")
    if any(run.head_sha != head for run in runs):
        raise RuntimeError(f"CI run head differs from default branch for {repo}")
    # Keep unrelated manual runs separate: same workflow and SHA do not establish
    # equal test coverage. Fully skipped runs remain available as quiet audit data.
    skipped = [run for run in runs if run.conclusion == "skipped"]
    active = [run for run in runs if run.conclusion != "skipped"]
    with ThreadPoolExecutor(max_workers=6) as pool:
        detailed = list(pool.map(lambda run: collect_jobs(repo, run), active))
    policies = workflow_policies(repo, head)
    if report.gh_json("api", f"repos/{repo}/commits/{branch_path}")["sha"] != head:
        raise RuntimeError(
            f"Default branch changed during CI collection for {repo}; retry"
        )
    return RepositoryCI(
        repo=repo,
        default_branch=branch,
        head_sha=head,
        latest_head_runs=detailed,
        skipped_runs=skipped,
        workflow_policies=policies,
    )
