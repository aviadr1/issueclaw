# issueclaw — Agent Skill Guide

issueclaw syncs Linear issues, projects, and documents bidirectionally with a git repo. Every entity is a plain markdown file under `linear/`. The repo is the source of truth — search it directly instead of calling the Linear API.

## Repo layout

```
linear/
  new/{TEAM}/{slug}.md             ← drop here to create a new issue
  teams/{TEAM}/issues/{ID}-{slug}.md
  projects/{slug}/_project.md
  projects/{slug}/updates/{date-author}.md
  initiatives/{slug}.md
  documents/{slug}.md
.sync/id-map.json                  ← maps file paths → Linear UUIDs (do not edit)
```

Teams: AI, ENG, WEB, MOB, BE, OPS, PRD, DSG

---

## Searching

The repo is fully local — grep is faster than any API call. When using Claude Code, prefer the **Grep** tool over bash grep.

```
# Issues by keyword
Grep pattern="transcription" path="linear/teams/*/issues/"

# Issues by status
Grep pattern="^status: In Progress" path="linear/teams/*/issues/"

# Issues by assignee
Grep pattern="^assignee: Aviad" path="linear/teams/*/issues/"

# Issues by label (YAML list item)
Grep pattern="^- Bug$" path="linear/teams/AI/issues/"

# Issues by team (scope the path)
Read files under linear/teams/AI/issues/

# Cross-entity search (issues + docs + projects)
Grep pattern="keyword" path="linear/"
```

When presenting results, always show: identifier, title, status, assignee, and the `url` from frontmatter.

---

## Creating a new issue

Drop a file in `linear/new/{TEAM}/{slug}.md`, commit, and push. CI creates the issue in Linear, writes the canonical file to `linear/teams/{TEAM}/issues/{ID}-{slug}.md`, and deletes the queue file.

```markdown
---
title: Your issue title here
status: Backlog
priority: 2
assignee: Name
labels:
- Bug
- Research
---

Description body here...
```

**Rules:**
- Never add `id`, `identifier`, `url`, `created`, or `updated` — Linear assigns those
- File must be in `linear/new/{TEAM}/` — never directly in `linear/new/` or `linear/teams/`
- Filename should match the title slug (e.g., `fix-login-bug.md` for "Fix login bug")

**Priority values:** 0=No priority, 1=Urgent, 2=High, 3=Medium, 4=Low

**Labels:** Bug, Feature, Improvement, TechDebt, HotFix, Regression, Research, Task, Story, ReleaseBlocking, DX, UX

---

## Updating an existing issue

Edit the markdown file at `linear/teams/{TEAM}/issues/{ID}-{slug}.md`, then commit and push. CI syncs changes to Linear automatically.

**Editable frontmatter fields:**

| Field | Type | Example |
|-------|------|---------|
| `title` | string | `Fix login bug` |
| `status` | string | `In Progress` |
| `priority` | int | `2` (High) |
| `assignee` | string | `Aviad` |
| `labels` | list | `- Bug` |
| `estimate` | int | `3` |
| `due_date` | date | `2026-04-01` |

**Read-only fields** (set by Linear, don't edit): `id`, `identifier`, `url`, `created`, `updated`

**To add a comment:** append a new `## Author - timestamp` section under `# Comments`:

```markdown
# Comments

## Aviad - 2026-03-14T10:00:00Z

Your comment text here.
```

---

## Creating a project status update

Add a new `.md` file under `linear/projects/{slug}/updates/` with frontmatter:

```markdown
---
health: onTrack
author: Name
---

Update body here...
```

Health values: `onTrack`, `atRisk`, `offTrack`

---

## Statuses reference

Issues: Backlog, Todo, Needs Refinement, Needs Designs, In Progress, Code Review, To QA, Product Verification, To Fix, Done, Canceled, Duplicate, Blocked, Triage

Projects: Backlog, Ready for Dev, Dev In Progress, Done, Needs Refinement, Needs Designs, Canceled

---

## CLI commands

```bash
# Install
curl -fsSL https://raw.githubusercontent.com/aviadr1/issueclaw/main/install.sh | sh

# Create entities directly (no git push needed)
issueclaw create issue --team AI --title "Fix login bug" --status Backlog --priority 2 \
  --assignee Aviad --label Bug --label Task \
  --description "Login fails when email contains a plus sign."

issueclaw create comment --issue AI-123 --body "Investigated. Root cause is the URL encoder."

issueclaw create project --name "Auth Revamp" --team ENG --team BE \
  --lead Aviad --priority 2 --target-date 2026-06-30

issueclaw create initiative --name "Q3 Security Hardening" \
  --owner Aviad --target-date 2026-09-30

issueclaw create document --title "Auth Revamp PRD" \
  --project auth-revamp --body "## Context\n..."

# Pull all Linear entities to local markdown files
issueclaw pull --api-key $LINEAR_API_KEY

# Push local changes to Linear (CI does this automatically on git push)
issueclaw push --api-key $LINEAR_API_KEY

# Show sync status (entity counts, teams, last sync)
issueclaw status

# Preview what would be pushed
issueclaw diff

# JSON output for scripts/agents
issueclaw --json create issue --team AI --title "..." --priority 2
issueclaw --json status

# Self-management
issueclaw self update       # Upgrade to latest from GitHub
issueclaw self detect       # Show version, executable, Python info
issueclaw self skill        # Print this guide
```

---

## When to use CLI vs git push

| Approach | Best for |
|----------|----------|
| `issueclaw create issue/project/initiative/document/comment` | Creating any entity immediately — no git commit needed, writes canonical file right away |
| Drop file in `linear/new/` + `git push` | Creating issues as part of a larger commit, or from a context without CLI access (CI handles it) |
| Edit file + `git push` | Updating existing issues — CI handles the Linear sync automatically |
| `issueclaw push` locally | Debugging, one-off pushes without CI, testing changes |
| `issueclaw pull` locally | Bootstrapping a new local clone, force-refreshing stale files |
