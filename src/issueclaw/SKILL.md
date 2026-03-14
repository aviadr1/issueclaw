# issueclaw — Agent Skill Guide

issueclaw syncs Linear issues, projects, and documents bidirectionally with a git repo. Every entity is a markdown file.

## Creating a new issue

Drop a file in `linear/new/{TEAM}/{slug}.md` with minimal frontmatter, then commit and push. CI creates the issue in Linear, writes the canonical file to `linear/teams/{TEAM}/issues/{ID}-{slug}.md`, and deletes the queue file.

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
- File must be in `linear/new/{TEAM}/` not `linear/new/` directly
- Never put a file directly in `linear/teams/` for a new issue

**Teams:** AI, ENG, WEB, MOB, BE, OPS, PRD, DSG

**Priority values:** 0=No priority, 1=Urgent, 2=High, 3=Medium, 4=Low

**Labels:** Bug, Feature, Improvement, TechDebt, HotFix, Regression, Research, Task, Story, ReleaseBlocking, DX, UX

## Updating an existing issue

Edit the markdown file at `linear/teams/{TEAM}/issues/{ID}-{slug}.md`:
- Change YAML frontmatter fields: `status`, `priority`, `assignee`, `labels`, `estimate`, `due_date`
- Edit the markdown body to change the description
- Add a `## Author - timestamp` section under `# Comments` to add a comment

Then commit and push. CI syncs changes to Linear automatically.

## Creating a project status update

Add a new `.md` file under `linear/projects/{slug}/updates/` with frontmatter:

```markdown
---
health: onTrack
author: Name
---

Update body here...
```

## Searching the repo

The git repo is the source of truth. Use grep on the `linear/` directory:

```bash
# Find issues by keyword
grep -rl "keyword" linear/teams/*/issues/

# Find by status
grep -rl "^status: In Progress" linear/teams/*/issues/

# Find by assignee
grep -rl "^assignee: Aviad" linear/teams/*/issues/

# Find by label
grep -rl "^- Bug$" linear/teams/AI/issues/
```

## CLI usage (alternative to git push)

issueclaw also provides direct CLI commands:

```bash
# Install
curl -fsSL https://raw.githubusercontent.com/aviadr1/issueclaw/main/install.sh | sh

# Pull all Linear entities to local markdown files
issueclaw pull --api-key $LINEAR_API_KEY

# Push local changes to Linear
issueclaw push --api-key $LINEAR_API_KEY

# Show sync status
issueclaw status

# Preview what would be pushed
issueclaw diff

# Self-management
issueclaw self update       # Upgrade to latest version
issueclaw self detect       # Show installation info
issueclaw self skill        # Print this skill guide
```
