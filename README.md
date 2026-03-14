# issueclaw: Issues as Code

**Bidirectional sync between Linear and Git using markdown files and git diffs.**

Issueclaw treats your project management data as code. Issues, projects, initiatives, and documents live as `.md` files in a git repository. Changes flow bidirectionally: edit a markdown file and push to update Linear, or let Linear webhooks update your git repo automatically. Git diffs are the change detection mechanism. Git merge is the conflict resolution strategy. No custom sync logic for problems git already solves.

Inspired by the [OpenClaw](https://github.com/openclaw/openclaw) philosophy of autonomous agents that execute real tasks on your infrastructure - issueclaw is an autonomous agent for your issue tracker.

## Quick Start

```bash
# Install (from GitHub — not yet on PyPI)
curl -fsSL https://raw.githubusercontent.com/aviadr1/issueclaw/main/install.sh | sh

# Or install manually with uv
uv tool install git+https://github.com/aviadr1/issueclaw.git

# Upgrade to latest
issueclaw self update

# Set up a new repo with workflows, secrets, and Linear webhook
export LINEAR_API_KEY=lin_api_...
issueclaw init --repo-dir /path/to/linear-git --webhook-url https://your-worker.workers.dev

# Pull all Linear data into a local repo
issueclaw pull --repo-dir /path/to/linear-git

# Filter by team
issueclaw pull --repo-dir /path/to/linear-git --teams AI,ENG

# Push local markdown changes to Linear
issueclaw push --repo-dir /path/to/linear-git

# Check sync status
issueclaw status --repo-dir /path/to/linear-git

# Preview what would be pushed to Linear
issueclaw diff --repo-dir /path/to/linear-git

# JSON output for scripts/agents
issueclaw --json status --repo-dir /path/to/linear-git

# Create entities directly (no git push required — writes files + updates id-map immediately)
# --description / --body accepts a file path or '-' for stdin
issueclaw create issue --team AI --title "Fix login bug" --priority 2 --assignee Aviad \
  --label Bug --description issue-body.md
echo "Root cause found." | issueclaw create comment --issue AI-123
issueclaw create project --name "Auth Revamp" --team ENG --lead Aviad
issueclaw create initiative --name "Q3 Security Hardening" --owner Aviad
issueclaw create document --title "Auth Revamp PRD" --project auth-revamp < prd.md

# Self-management
issueclaw self detect       # Show version, executable, Python info
issueclaw self skill        # Print the agent usage guide (SKILL.md)
issueclaw self update       # Upgrade to latest from GitHub
```

## Current Status

**All 4 phases are complete and tested end-to-end in production.**

- **Phase 1 (Pull)**: `issueclaw pull` syncs all Linear data into rich markdown files (3500+ entities).
- **Phase 2 (Webhook Pull)**: Linear changes sync to git in real-time via CF Worker + GitHub Actions.
- **Phase 3 (Push)**: Edit markdown, `git push`, and changes flow to Linear automatically via GitHub Actions.
- **Phase 4 (Polish)**: Status/assignee field resolution, `issueclaw status` and `issueclaw diff` commands.

The developer workflow is just git — `git pull` to get changes, edit files, `git push` to sync back. issueclaw itself only runs in CI/CD.

---

## Table of Contents

- [Philosophy](#philosophy)
- [Product Requirements](#product-requirements)
- [Architecture](#architecture)
- [File Structure](#file-structure)
- [Markdown File Format](#markdown-file-format)
- [Sync Protocol](#sync-protocol)
- [Loop Prevention](#loop-prevention)
- [Implementation Guide](#implementation-guide)
- [Limitations and Tradeoffs](#limitations-and-tradeoffs)
- [Build Phases](#build-phases)

---

## Philosophy

### Why Issues as Code?

Project management tools are information silos. You can't grep your backlog. You can't `git blame` an issue description to see who changed the acceptance criteria. You can't create a branch that atomically modifies code AND its related issues.

Issueclaw breaks this silo by storing Linear data as plain markdown files in git. This gives you:

1. **Grep over your entire backlog** - ripgrep searches thousands of issues in milliseconds, with full regex support. No API pagination, no rate limits, no network latency.

2. **Git history for issues** - `git log --follow AI-123.md` shows the full lifecycle of an issue. `git blame` shows who changed what and when.

3. **Atomic code + issue changes** - A single commit can change code AND update the related issue's status. Merging a PR merges the issue changes. Reverting a PR reverts the issue changes.

4. **Offline capable** - Work on issues on a plane. Commit locally. Sync when you're back online.

5. **Reviewable changes** - "Move these 5 issues to Done" is a PR diff that goes through code review.

6. **Branch = workspace** - A feature branch can have its own issue modifications that only take effect when the branch merges.

### Design Principles

- **Git is the master** - When there's a conflict, the git version wins. Linear is a view into git, not the other way around.
- **Leverage git, don't reinvent it** - Change detection is `git diff`. Conflict resolution is `git merge`. History is `git log`. No custom sync state machines for problems git already solves.
- **Minimal API calls** - Parse git diffs to send only changed fields to Linear. One field change = one minimal API call, not a full entity update.
- **Event-driven, not polling** - Linear webhooks push changes to git in real-time. No periodic full-sync scanning the entire workspace.
- **Zero external infrastructure** - GitHub Actions is the compute layer. One optional Cloudflare Worker (20 lines, free tier) is the only external component.

---

## Product Requirements

### PRD: issueclaw

**Problem**: Linear data is locked in an API. Searching across issues requires paginated API calls. There's no way to grep, cross-reference, or version-control project management data alongside code. AI coding assistants (like Claude Code) work best with local files they can grep and read instantly, but must make slow API calls to interact with Linear.

**Solution**: A bidirectional sync tool that mirrors Linear data as markdown files in a git repository, using git diffs as the change detection mechanism and GitHub Actions as the compute layer.

### Functional Requirements

#### FR-1: Linear to Git sync (Pull direction)
- **FR-1.1**: On any Linear entity change (issue, project, initiative, document, comment), the corresponding `.md` file in git must be updated within 30 seconds.
- **FR-1.2**: Linear webhooks deliver entity IDs and changed fields, but use IDs for relationships (e.g., `stateId` instead of state name). The sync must re-fetch the full entity via the Linear API to render complete markdown.
- **FR-1.3**: The sync must handle all Linear entity types: issues, projects, initiatives, milestones, documents, and comments.
- **FR-1.4**: Comments must be embedded in their parent issue's `.md` file, not as separate files.

#### FR-2: Git to Linear sync (Push direction)
- **FR-2.1**: On any push to `main` that modifies files under `linear/`, the corresponding Linear entities must be updated.
- **FR-2.2**: The sync must parse `git diff` to determine only the changed fields and send minimal API updates (not full entity rewrites).
- **FR-2.3**: New `.md` files must create new Linear entities. The assigned Linear UUID and identifier must be written back to the file's frontmatter.
- **FR-2.4**: Deleted `.md` files must archive/cancel the corresponding Linear entity.
- **FR-2.5**: The sync must handle field mapping between markdown frontmatter field names and Linear API field names.

#### FR-3: Loop prevention
- **FR-3.1**: Sync bot commits must use a dedicated author identity (`issueclaw-bot`).
- **FR-3.2**: The push workflow must skip commits authored by the sync bot.
- **FR-3.3**: When the pull direction writes a file that already matches the current state (e.g., after a push just updated Linear), `git diff --staged --quiet` must detect no change and skip committing.

#### FR-4: Conflict handling
- **FR-4.1**: When both git and Linear change the same entity simultaneously, the pull direction commits the Linear version, which may create a git merge conflict if there are local changes.
- **FR-4.2**: Merge conflicts are resolved using standard git merge tools. The resolved version is pushed to Linear on the next push sync.

#### FR-5: Initial sync
- **FR-5.1**: A one-time full sync command must pull all Linear data into the `.md` file structure.
- **FR-5.2**: The initial sync must build the `.sync/id-map.json` mapping file paths to Linear UUIDs.
- **FR-5.3**: The initial sync must support filtering by team (to avoid syncing the entire workspace if not needed).

#### FR-6: Concurrency safety
- **FR-6.1**: All GitHub Actions workflows must use a concurrency group to prevent parallel runs from conflicting.
- **FR-6.2**: The concurrency group must queue (not cancel) concurrent runs.

### Non-Functional Requirements

- **NFR-1**: The webhook proxy (Cloudflare Worker) must be deployable in under 5 minutes.
- **NFR-2**: The system must work with GitHub Actions free tier (2000 minutes/month).
- **NFR-3**: No state outside of git. All sync metadata lives in `.sync/` within the repository.
- **NFR-4**: The system must handle workspaces with 10,000+ issues without degradation in the webhook (pull) direction. Only the initial sync scales with workspace size.

### Out of Scope

- Real-time collaborative editing of `.md` files (use branches and PRs).
- Syncing Linear attachments as binary files (store URLs only).
- Fine-grained permissions mirroring Linear's access control.
- Two-way sync of Linear's UI-only features (views, favorites, notifications).
- Syncing to multiple git repositories from one Linear workspace.

---

## Architecture

### System Overview

```
                         ┌─────────────────────────────────────────┐
                         │              GitHub Repository           │
                         │                                         │
                         │  linear/                                │
                         │  ├── teams/AI/issues/AI-123.md          │
                         │  ├── projects/chapter-detection/        │
                         │  ├── initiatives/q1-roadmap.md          │
                         │  └── documents/arch-overview.md         │
                         │                                         │
                         │  .sync/                                 │
                         │  ├── id-map.json                        │
                         │  └── state.json                         │
                         └────────────┬──────────────┬─────────────┘
                                      │              │
                              push to main     repository_dispatch
                              (paths: linear/**)     │
                                      │              │
                                      ▼              │
                         ┌─────────────────┐         │
                         │ issueclaw-push.yaml │         │
                         │ (Git → Linear)   │         │
                         │                  │         │
                         │ 1. git diff      │         │
                         │ 2. parse changes │         │
                         │ 3. Linear API    │         │
                         │ 4. commit IDs    │         │
                         └────────┬────────┘         │
                                  │                   │
                                  ▼                   │
                         ┌──────────────┐    ┌────────┴────────┐
                         │    Linear    │    │ linear-webhook   │
                         │              │    │ .yaml            │
                         │              │    │                  │
                         │  Issues      │    │ 1. parse payload │
                         │  Projects    │    │ 2. write .md     │
                         │  Documents   │    │ 3. git commit    │
                         │  Initiatives │    │                  │
                         └──────┬───────┘    └────────┬────────┘
                                │                      ▲
                                │ webhook POST         │ repository_dispatch
                                ▼                      │
                         ┌──────────────┐              │
                         │ CF Worker    │──────────────┘
                         │ (20 lines)   │
                         │ webhook proxy│
                         └──────────────┘
```

### Component Responsibilities

| Component | Responsibility |
|-----------|---------------|
| `linear/` directory | Markdown files representing Linear entities. Source of truth. |
| `.sync/id-map.json` | Maps file paths to Linear UUIDs. Built during initial sync, maintained by push workflow. |
| `.sync/state.json` | Stores last sync timestamps and commit hashes. Used by initial sync and recovery. |
| `issueclaw-push.yaml` | GitHub Actions workflow. Triggers on push to `linear/**`. Parses git diff, calls Linear API. |
| `issueclaw-webhook.yaml` | GitHub Actions workflow. Triggers on `repository_dispatch`. Writes `.md` from webhook payload. |
| CF Worker | Cloudflare Worker. Receives Linear webhook, validates signature, forwards as GitHub `repository_dispatch`. |
| `scripts/issueclaw/` | Python scripts for push, pull, initial sync, and webhook application. |

### Data Flow: Human edits an issue

```
1. Human changes status in AI-123.md:    "In Progress" → "Done"
2. Human commits and pushes to main
3. issueclaw-push.yaml triggers (author != sync-bot ✓)
4. Script runs: git diff HEAD~1..HEAD -- linear/
5. Detects: M linear/teams/AI/issues/AI-123.md
6. Parses diff: only `status` field changed
7. Calls Linear API: save_issue(id=uuid, state="Done")
8. Linear updates the issue
9. Linear fires webhook (issue updated)
10. CF Worker forwards to GitHub repository_dispatch
11. issueclaw-webhook.yaml triggers
12. Script writes AI-123.md from webhook payload
13. File already says "Done" → git diff --staged --quiet → true
14. No commit. Loop stops.
```

### Data Flow: Someone changes an issue in Linear UI

```
1. User changes AI-123 status to "Done" in Linear UI
2. Linear fires webhook with full issue payload
3. CF Worker receives POST, validates signature
4. CF Worker calls GitHub API: repository_dispatch(event_type="linear_webhook", payload=...)
5. issueclaw-webhook.yaml triggers
6. Script extracts entity from payload, writes AI-123.md with updated frontmatter
7. git add + commit (author: issueclaw-bot)
8. git push
9. issueclaw-push.yaml triggers but skips (author == sync-bot)
10. Done. No loop.
```

---

## File Structure

```
repo-root/
├── linear/
│   ├── new/                            ← drop new issue files here to create them
│   │   ├── AI/
│   │   │   └── fix-login-bug.md        ← CI creates the issue, moves to teams/
│   │   └── ENG/
│   │       └── refactor-api-client.md
│   ├── teams/
│   │   ├── AI/
│   │   │   └── issues/
│   │   │       ├── AI-123-fix-login-bug.md
│   │   │       ├── AI-124-implement-chapter-detection.md
│   │   │       └── AI-125-update-video-moderation.md
│   │   └── ENG/
│   │       └── issues/
│   │           └── ENG-42-refactor-api-client.md
│   ├── projects/
│   │   ├── chapter-detection/
│   │   │   ├── _project.md
│   │   │   ├── milestones/
│   │   │   │   └── mvp.md
│   │   │   └── updates/
│   │   │       └── 2026-02-17-oz-shaked.md
│   │   └── metrics-platform/
│   │       └── _project.md
│   ├── initiatives/
│   │   └── q1-2026-roadmap.md
│   └── documents/
│       └── architecture-overview.md
├── .sync/
│   ├── id-map.json
│   └── state.json
├── .github/
│   └── workflows/
│       ├── issueclaw-push.yaml
│       └── issueclaw-webhook.yaml
└── workers/
    └── issueclaw-webhook-proxy/
        ├── worker.js
        └── wrangler.toml
```

### Path conventions

- **New issue queue**: `linear/new/{TEAM_KEY}/{title-slug}.md` — drop files here to create new issues; CI moves them to `linear/teams/` after creation
- Issues: `linear/teams/{TEAM_KEY}/issues/{IDENTIFIER}-{title-slug}.md` (e.g., `linear/teams/AI/issues/AI-123-fix-login-bug.md`)
- Projects: `linear/projects/{name-slug}/_project.md` (e.g., `linear/projects/metrics-platform/_project.md`)
- Project updates: `linear/projects/{name-slug}/updates/{date-author}.md` (e.g., `linear/projects/metrics-platform/updates/2026-03-13-aviad-rozenhek.md`)
- Milestones: `linear/projects/{name-slug}/milestones/{name}.md`
- Initiatives: `linear/initiatives/{name-slug}.md`
- Documents: `linear/documents/{title-slug}.md`

File names include slugified titles for readability. Issue identifiers (AI-123) are stable; the slug suffix is derived from the title at sync time.

---

## Markdown File Format

### Issue

```markdown
---
id: "f47ac10b-58cc-4372-a567-0e02b2c3d479"
identifier: "AI-123"
title: "Implement chapter detection"
status: "In Progress"
priority: 2
assignee: "aviad@gigaverse.ai"
labels:
  - "feature"
  - "ai"
project: "Chapter Detection"
milestone: "MVP"
parent: "AI-100"
estimate: 3
due_date: "2026-04-01"
started_at: "2026-02-01T10:00:00Z"
created: "2026-01-15T10:00:00Z"
updated: "2026-03-01T14:30:00Z"
url: "https://linear.app/gigaverse/issue/AI-123"
---

# AI-123: Implement chapter detection

Implement chapter detection for livestreams based on speaker
composition changes and breaks, not topics.

Returns null for single-speaker streams.

# Comments

## aviad@gigaverse.ai - 2026-02-15T09:00:00Z
<!-- comment-id: d290f1ee-6c54-4b01-90e6-d701748f0851 -->

Started working on this. Using Gemini for initial analysis.

## john@gigaverse.ai - 2026-02-20T11:00:00Z
<!-- comment-id: 7c9e6679-7425-40de-944b-e07fc1f90ae7 -->

Looks good! Can we add break detection too?
```

### Issue frontmatter field mapping

| Frontmatter field | Linear API field | Notes |
|-------------------|------------------|-------|
| `id` | `id` | UUID. Immutable. Set on create. |
| `identifier` | `identifier` | Human-readable (AI-123). Immutable. |
| `title` | `title` | Required on create. |
| `status` | `state.name` | Maps to Linear workflow state name. |
| `priority` | `priority` | 0=None, 1=Urgent, 2=High, 3=Normal, 4=Low. |
| `assignee` | `assignee.name` | User name. Null to unassign. |
| `labels` | `labels.nodes[].name` | List of label names. |
| `project` | `project.name` | Project name. |
| `milestone` | `projectMilestone.name` | Milestone name within the project. |
| `parent` | `parent.identifier` | Parent issue identifier (for sub-issues). |
| `estimate` | `estimate` | Numeric estimate value. |
| `due_date` | `dueDate` | ISO date. |
| `started_at` | `startedAt` | When work began. |
| `completed_at` | `completedAt` | When marked done. |
| `canceled_at` | `canceledAt` | When canceled. |
| `created` | `createdAt` | Read-only. Set by Linear. |
| `updated` | `updatedAt` | Read-only. Set by Linear. |
| `url` | `url` | Read-only. Linear URL. |

### Project

```markdown
---
id: "b7983d06-00c2-46c7-92a2-dd5a5add56df"
name: "Metrics Platform"
slug: "metrics-platform"
status: "Ready for Dev"
health: "onTrack"
progress: 0.75
scope: 36.0
lead: "Mateusz"
priority: 2
start_date: "2026-02-12"
labels:
  - "Metrics"
teams:
  - "WEB"
  - "ENG"
members:
  - "Aviad Rozenhek"
  - "Mateusz"
  - "Oz Shaked"
url: "https://linear.app/gigaverse/project/metrics-platform-7bb22805ba90"
---

# Metrics Platform

Treat data infrastructure identically to application code...

# Milestones

- **MVP** (done) - 100%
  Target: 2026-03-01
  First release

# Status Updates

- [2026-02-17T11:04:21Z](updates/2026-02-17-oz-shaked.md) by Oz Shaked [onTrack]

# Initiatives

- Community metrics

# Documents

- Architecture Design
- Data Recovery Playbook
```

### Initiative

```markdown
---
id: "0ddf8c1c-uuid"
name: "Community metrics"
status: "Active"
health: "atRisk"
owner: "Aviad"
target_date: "2026-06-30"
url: "https://linear.app/gigaverse/initiative/community-metrics"
---

# Community metrics

Detailed content about the initiative goals and approach...

# Projects

- Metrics Platform
- Analytics Dashboard
```

### Comment format within issues

Comments are embedded in the issue file under a `# Comments` section. Each comment is a level-2 heading with the author and timestamp. The Linear comment UUID is stored in an HTML comment for the sync tool to track.

```markdown
# Comments

## author@email.com - ISO-8601-timestamp
<!-- comment-id: linear-comment-uuid -->

Comment body in markdown.
```

New comments are added by appending a new `## ` section. Deleted comments are removed by deleting the section. Edited comments modify the body below the heading.

### Project status updates

Project status updates are stored as individual files under `linear/projects/{slug}/updates/`, not inline in the project file. The project file contains reference links:

```markdown
# Status Updates

- [2026-03-13T21:00:00Z](updates/2026-03-13-aviad-rozenhek.md) by Aviad Rozenhek [onTrack]
```

Each update file has its own frontmatter:

```markdown
---
id: "update-uuid"
author: "Aviad Rozenhek"
health: "onTrack"
created: "2026-03-13T21:00:00Z"
---

Update content in full markdown.
```

To create a new project update, add a new `.md` file under `updates/` and push. The push workflow will call the `projectUpdateCreate` mutation in Linear.

---

## Sync Protocol

### Initial Sync (Pull)

Run to bootstrap or refresh the `.md` file structure:

```bash
# Install issueclaw
uv tool install issueclaw

# Pull all teams
issueclaw pull --repo-dir /path/to/linear-git

# Pull specific teams only
issueclaw pull --repo-dir /path/to/linear-git --teams AI,ENG
```

1. Fetches all issues per team with inline comments (50 per page).
2. Fetches all projects with milestones, status updates, members, initiatives, documents (5 per page due to API complexity limits).
3. Fetches all initiatives with linked projects.
4. Fetches all documents with project linkage.
5. Renders each entity as a `.md` file with rich content.
6. Builds `.sync/id-map.json` mapping file paths to UUIDs.
7. Saves `.sync/state.json` incrementally after each team for crash resilience.

This is the only expensive operation. It scales with workspace size but supports resumption after interruption.

### Push Sync (Git to Linear)

Triggered by: push to `main` modifying `linear/**` files, where commit author is not `issueclaw-bot`.

```
1. Scan linear/new/ for any queue files (processed regardless of git diff,
   so retries work if a previous CI run failed mid-way).

2. Run: git diff --name-status HEAD~1..HEAD -- linear/
   Output: A/M/D status for each changed file

3. For each NEW ISSUE queue file (linear/new/{TEAM}/{slug}.md):
   a. Parse frontmatter: title, status, priority, assignee, labels
   b. Resolve team ID, state ID, assignee ID, label IDs via Linear API
   c. Call Linear API issueCreate mutation
   d. Write canonical file to linear/teams/{TEAM}/issues/{ID}-{slug}.md
   e. Delete the queue file
   f. Update .sync/id-map.json

4. For each other ADDED file:
   a. Parse frontmatter + body
   b. Determine entity type from path (projects/updates/, etc.)
   c. Call Linear API to create the entity
   d. Update .sync/id-map.json

5. For each MODIFIED file:
   a. Run: git show HEAD~1:{path} to get previous version
   b. Parse old and new frontmatter
   c. Diff field-by-field to find only changed fields
   d. Diff body to detect description changes
   e. Diff comments section to detect added/removed/edited comments
   f. Call Linear API with ONLY changed fields
   g. Call comment APIs for comment changes

4. For each DELETED file:
   a. Look up UUID from .sync/id-map.json
   b. Call Linear API to archive/cancel
   c. Remove from id-map

5. Commit any changes (ID assignments, updated timestamps)
```

### Pull Sync (Linear to Git via Webhook)

Triggered by: `repository_dispatch` event from the Cloudflare Worker.

```
1. Parse webhook payload:
   - action: "create" | "update" | "remove"
   - type: "Issue" | "Comment" | "Project" | ...
   - data: { id, ... } (IDs for relationships, not full objects)

2. For "create" or "update":
   - Re-fetch full entity via Linear API (resolves stateId → name, teamId → key, etc.)
   - Render entity to .md format
   - Determine file path from entity data
   - Write to file path, handle renames on title changes
   - For comments: re-fetch parent issue and re-render entire file

3. For "remove":
   - Look up file path from .sync/id-map.json
   - Delete the file
   - Remove from id-map

4. git add -A
5. git diff --cached --quiet || git commit + push
```

Note: Linear webhook payloads use IDs for relationships (e.g., `stateId`, `teamId`) rather than nested objects. The apply-webhook command re-fetches the full entity via the Linear API to render complete markdown with resolved names.

### Diff Parsing Strategy

The push sync must parse git diffs of structured `.md` files. The strategy:

1. **Don't parse the unified diff format.** Instead, use `git show HEAD~1:{path}` to get the full previous file content.
2. **Parse both old and new files** into (frontmatter_dict, body_string, comments_list).
3. **Diff the frontmatter dicts** field-by-field. Only changed fields become API call parameters.
4. **Diff body strings.** If different, send the new description.
5. **Diff comments by comment-id.** New IDs = new comments. Missing IDs = deleted. Changed body = edited.

This is more robust than parsing unified diff hunks, which can be ambiguous for YAML.

---

## Loop Prevention

The bidirectional sync creates a potential infinite loop:

```
Git change → push to Linear → webhook → pull to git → push to Linear → ...
```

Three mechanisms prevent this:

### 1. Author gating (primary)

The push workflow only runs for human commits:

```yaml
if: github.event.head_commit.author.name != 'issueclaw-bot'
```

The pull workflow always commits as `issueclaw-bot`. So pull commits never trigger pushes.

### 2. No-op detection (secondary)

When a push updates Linear, and Linear fires a webhook, the pull workflow regenerates the `.md` file. But since the push already set the correct values, the regenerated file matches what's in git:

```bash
git diff --staged --quiet  # true → no commit → no push → loop stops
```

### 3. Concurrency group (safety)

Both workflows use the same concurrency group to prevent race conditions:

```yaml
concurrency:
  group: issueclaw-sync
  cancel-in-progress: false  # queue, don't cancel
```

---

## Implementation Guide

### Cloudflare Worker (Webhook Proxy)

The worker receives Linear webhook POSTs and forwards them as GitHub `repository_dispatch` events.

```javascript
// workers/issueclaw-webhook-proxy/worker.js
export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    const body = await request.text();
    const signature = request.headers.get("linear-signature");

    // Validate webhook signature
    const encoder = new TextEncoder();
    const key = await crypto.subtle.importKey(
      "raw",
      encoder.encode(env.LINEAR_WEBHOOK_SECRET),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["sign"]
    );
    const sig = await crypto.subtle.sign("HMAC", key, encoder.encode(body));
    const expected = [...new Uint8Array(sig)]
      .map(b => b.toString(16).padStart(2, "0"))
      .join("");

    if (signature !== expected) {
      return new Response("Invalid signature", { status: 401 });
    }

    const payload = JSON.parse(body);

    // Forward to GitHub as repository_dispatch
    const response = await fetch(
      `https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GITHUB_TOKEN}`,
          Accept: "application/vnd.github.v3+json",
          "User-Agent": "issueclaw-webhook-proxy",
        },
        body: JSON.stringify({
          event_type: "linear-webhook",
          client_payload: {
            action: payload.action,
            type: payload.type,
            data: payload.data,
            updatedFrom: payload.updatedFrom || {},
          },
        }),
      }
    );

    if (!response.ok) {
      return new Response(`GitHub API error: ${response.status}`, { status: 502 });
    }

    return new Response("OK", { status: 200 });
  },
};
```

### GitHub Actions Workflows

#### Push workflow (Git to Linear)

```yaml
# .github/workflows/issueclaw-push.yaml
name: Push Changes to Linear

on:
  push:
    branches: [main]
    paths: ['linear/**']

permissions:
  contents: write

jobs:
  push-to-linear:
    runs-on: ubuntu-latest
    if: github.event.head_commit.author.name != 'issueclaw-bot'
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 2  # Need parent commit for diff

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - uses: astral-sh/setup-uv@v4

      - name: Install issueclaw
        run: uv tool install git+https://github.com/aviadr1/issueclaw.git

      - name: Push changes to Linear
        env:
          LINEAR_API_KEY: ${{ secrets.LINEAR_API_KEY }}
        run: issueclaw push

      - name: Commit updated sync state
        run: |
          git config user.name "issueclaw-bot"
          git config user.email "issueclaw-bot@users.noreply.github.com"
          git add .sync/ linear/   # linear/ captures queue file moves on issue creation
          if git diff --cached --quiet; then
            echo "No sync state changes"
          else
            git commit -m "sync: update sync state after push to Linear"
            git push
          fi
```

#### Webhook workflow (Linear to Git)

```yaml
# .github/workflows/issueclaw-webhook.yaml
name: Apply Linear Webhook

on:
  repository_dispatch:
    types: [linear-webhook]

permissions:
  contents: write

jobs:
  apply-webhook:
    runs-on: ubuntu-latest
    concurrency:
      group: issueclaw-webhook
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - uses: astral-sh/setup-uv@v4

      - name: Install issueclaw
        run: uv tool install git+https://github.com/aviadr1/issueclaw.git

      - name: Apply webhook payload
        env:
          LINEAR_API_KEY: ${{ secrets.LINEAR_API_KEY }}
          WEBHOOK_PAYLOAD: ${{ toJson(github.event.client_payload) }}
        run: issueclaw apply-webhook

      - name: Commit and push changes
        env:
          WEBHOOK_TYPE: ${{ github.event.client_payload.type }}
          WEBHOOK_ACTION: ${{ github.event.client_payload.action }}
        run: |
          git config user.name "issueclaw-bot"
          git config user.email "issueclaw-bot@users.noreply.github.com"
          git add -A
          if git diff --cached --quiet; then
            echo "No changes to commit"
          else
            git commit -m "sync: apply Linear webhook ($WEBHOOK_TYPE $WEBHOOK_ACTION)"
            git push
          fi
```

### issueclaw Python Package

The tool is a pip-installable Python package (`uv tool install issueclaw`) with these modules:

| Module | Purpose |
|--------|---------|
| `issueclaw.commands.init` | Repo setup: saves API key, copies workflows, sets GitHub secrets, creates Linear webhook, runs initial pull |
| `issueclaw.commands.pull` | Initial pull sync: fetches all Linear data, renders to `.md`, builds id-map |
| `issueclaw.commands.apply_webhook` | Webhook pull: re-fetches entity by ID, renders to `.md`, handles create/update/remove |
| `issueclaw.commands.push` | Push sync: detects git changes, diffs markdown, resolves fields, calls Linear mutations |
| `issueclaw.commands.status` | Shows sync state summary: entity counts, teams, last sync |
| `issueclaw.commands.diff_cmd` | Previews field-level changes that would be pushed |
| `issueclaw.commands.create` | `create issue/project/initiative/document/comment`: direct CLI creation, no git push needed |
| `issueclaw.commands.self_cmd` | Self-management: `self update`, `self detect`, `self skill` |
| `issueclaw.linear_client` | Async GraphQL client with pagination, rate limit handling, connection reuse, mutations |
| `issueclaw.diff` | Field-level markdown diff: frontmatter, body, and comments |
| `issueclaw.models` | Pydantic models for all Linear entity types |
| `issueclaw.render` | Markdown renderer: YAML frontmatter + entity heading + body + sections |
| `issueclaw.parse` | Markdown parser: extracts frontmatter, body, comments |
| `issueclaw.paths` | Path conventions: `entity_path()`, `parse_entity_path()`, `slugify()` |
| `issueclaw.sync_state` | `.sync/` management: id-map.json, state.json |

### Secrets Required

| Secret | Where | Purpose |
|--------|-------|---------|
| `LINEAR_API_KEY` | GitHub Actions | Push script calls Linear API |
| `LINEAR_WEBHOOK_SECRET` | Cloudflare Worker | Validate webhook signatures |
| `GITHUB_TOKEN` | Cloudflare Worker | Trigger repository_dispatch |
| `GITHUB_REPO` | Cloudflare Worker env | Target repo (e.g., `org/repo`) |

---

## Limitations and Tradeoffs

### What works well

- **Search**: Grep across all issues is instant and supports full regex.
- **History**: Full git history for every entity change.
- **Batch changes**: Modify many issues in one commit, one PR review.
- **Offline**: Full local copy, commit without network.
- **AI assistant friendly**: Claude Code can read/grep/edit `.md` files directly instead of making API calls.

### What doesn't work

- **Staleness**: Git copy is only as fresh as the last webhook sync. If the webhook proxy is down, data drifts.
- **Attachments**: Binary files (screenshots, PDFs) are stored as URLs only, not downloaded to git. Viewing them requires network access.
- **Comments threading**: Linear supports threaded replies. The flat `## Comments` section loses threading hierarchy. Parent comment IDs can be stored in HTML comments but the visual nesting is lost.
- **Permissions**: Git repo access is all-or-nothing. Linear's team/project-level permissions don't translate.
- **Real-time collaboration**: Two people editing the same `.md` file will create a merge conflict. Linear's UI handles concurrent edits seamlessly.
- **Views and filters**: Linear's saved views, favorites, and notification settings are UI-only and not synced.
- **Reactions and emoji**: Not represented in the markdown format.

### Scaling characteristics

| Dimension | Behavior |
|-----------|----------|
| Workspace size (initial sync) | O(total entities). Runs once. |
| Webhook sync (ongoing) | O(1) per change. Independent of workspace size. |
| Push sync | O(changed files in commit). Parsed from git diff. |
| Git repo size | Grows with issue count. 10K issues at ~2KB each = ~20MB. Git handles this fine. |
| API rate limits | Push direction makes one API call per changed field. Webhook direction makes zero API calls. |

---

## Build Phases

### Phase 1: Read-only pull (Linear to Git) - COMPLETE
- `issueclaw pull`: Full sync of all entities to `.md` files (3500+ entities).
- Markdown rendering for issues, projects, initiatives, documents with comments.
- **Value**: Instant grep over entire backlog. Zero risk (read-only).

### Phase 2: Webhook-driven pull (real-time) - COMPLETE
- Cloudflare Worker webhook proxy (validates HMAC-SHA256, forwards to GitHub).
- `issueclaw apply-webhook`: Re-fetches entity via API, renders markdown, writes file.
- Concurrency groups prevent push race conditions.
- **Value**: Real-time mirror. Changes appear in git within seconds.

### Phase 3: Push sync (Git to Linear) - COMPLETE
- `issueclaw push`: Detects git changes via `git diff HEAD~1`, diffs markdown field-by-field.
- Pushes title, description, priority, estimate, due date changes. Creates comments.
- Archives issues on file deletion. Strips entity headings to prevent round-trip duplication.
- Loop prevention via author gating (`issueclaw-bot` commits are skipped).
- **New issue queue**: Drop a file in `linear/new/{TEAM}/` with title/priority/assignee/labels — CI creates the issue in Linear and moves the file to the canonical path. Queue is always drained on push (not just on first commit of the file).
- **Value**: Full bidirectional sync. Edit issues as markdown, push, done. Create new issues by dropping files in the queue.

### Phase 4: Polish - COMPLETE
- `issueclaw status`: Shows entity counts, teams, and last sync timestamp.
- `issueclaw diff`: Previews field-level changes that would be pushed to Linear.
- `issueclaw self update/detect/skill`: Self-management and bundled agent guide.
- `install.sh`: One-liner installer via `uv tool install git+...`.
- Status field resolution: state name → stateId via team workflow states API.
- Assignee field resolution: user name → assigneeId via workspace users API.
- All commands support `--json` mode for scripting and AI agents.

**Remaining items (not yet implemented):**
- Image handling strategy (Linear uploads need auth tokens).
- Support for issue relations (blocks, blocked-by, related).
- Webhook delivery failure detection and recovery.

### Phase 5: Open Source Ready (TODO)

Currently issueclaw works for a single Linear workspace → single GitHub repo setup where the user deploys their own CF Worker. To make it useful for anyone:

- **GitHub App**: Replace the per-user CF Worker with a hosted GitHub App.
  - Users install the app on their repo (one click).
  - Linear webhooks go to the app's endpoint, which triggers `repository_dispatch` using the app's installation token.
  - No Cloudflare account, no worker deployment, no `GITHUB_TOKEN` management.
  - Routing: each installation gets a unique webhook URL (e.g., `https://issueclaw.example.com/webhook/<installation_id>`). The Linear webhook is created pointing to this URL.
  - Storage: KV/database maps installation IDs to repo info.
  - The `issueclaw init` command would: detect the GitHub App installation, create the Linear webhook pointing to the app, copy workflows, set secrets, run initial pull.

- **Multi-repo support**: One Linear workspace syncing to multiple repos (e.g., per-team repos).
  - Requires the GitHub App to route webhooks based on team/project.

- **`issueclaw init` improvements**:
  - Detect existing GitHub App installation automatically.
  - Interactive team selection during init (show available teams, let user pick).
  - Validate LINEAR_API_KEY before proceeding.

- **Hosting the GitHub App**:
  - Option A: CF Worker + KV (lightweight, free tier).
  - Option B: Vercel/Netlify serverless function.
  - Option C: Fly.io for a persistent service if needed.
  - The app logic is essentially the current `worker.js` plus installation token management.
