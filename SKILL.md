---
name: juju-pr-review
description: >
  Deep multi-lens code review for Juju PRs using parallel specialist agents.
  Use whenever asked to review a PR, do a code review, critique code changes,
  assess code quality, or check a branch before merge in the Juju repository.
  Produces a structured Markdown report with findings sorted by severity.
  Trigger on: "review this PR", "review PR #N", "code review for #XXXX",
  "critique my changes", "review my branch", "look at the code", or any
  request to assess quality of Juju code changes — even if the user doesn't
  say "review" explicitly. If the user is in a Juju repo and mentions a PR
  number or asks about their changes, use this skill.
---

# Juju PR Review Skill

A structured code review workflow that spawns parallel specialist agents, each
focused on a different dimension of quality, then merges their findings into a
single report. The review is done entirely from the local checkout — no large
code diffs are fetched from GitHub.

## Configuration

Check whether `~/.config/juju-pr-review/config.sh` exists.

**If missing**, create it:
```sh
mkdir -p ~/.config/juju-pr-review
cat > ~/.config/juju-pr-review/config.sh << 'EOF'
JUJU_REVIEW_REPORTS=~/copilot-sessions/artefacts
EOF
```
Inform the user of the default and that they can edit the file at any time.

**If present**, source it:
```sh
source ~/.config/juju-pr-review/config.sh
```

Use `$JUJU_REVIEW_REPORTS` as the report output directory throughout.

## Review Lenses

Six lenses are available. Present this menu and confirm which to use.
The default (L1+L2+L3) is what most reviews need; offer L4, L5, and L6 as
opt-in additions when the PR touches tests, DB code, or channel/goroutine code.

| ID | Lens | Focus | Default |
|----|------|-------|:-------:|
| L1 | Architecture alignment | Layer boundaries, import rules, transaction scope | on |
| L2 | Go idioms | Error handling, naming, interfaces, context, godoc | on |
| L3 | Juju style & idioms | sqlair patterns, DDD conventions, test structure, gci | on |
| L4 | Test coverage | Edge cases, missing scenarios, stress candidates | off |
| L5 | Database & performance | N+1 queries, bulk ops, chunking, transaction scope | off |
| L6 | Synchronization & concurrency | Channel lifecycle, goroutine safety, worker shutdown, race conditions | off |

Ask the user which lenses to activate, or proceed with the default (L1+L2+L3)
if they want to get started quickly.

## Workflow

### Step 1 — Gather PR context

Fetch PR metadata (title, description, file list) from GitHub. This is
lightweight — metadata only, no code diff:

```sh
gh pr view --repo juju/juju --json number,title,body,headRefName,baseRefName,author,additions,deletions,files
```

If no PR number was given, run this against the current branch (omit the PR
number argument and let `gh` infer it). If `gh` can't find a PR, fall back to
reading `git log --oneline -5` and `git diff --name-only origin/HEAD...HEAD`
to understand what changed.

From the file list, identify:
- Which layers are touched (`apiserver/`, `domain/`, `internal/worker/`, etc.)
- What pattern the PR is implementing (new feature, refactor, bug fix)
- Any predecessor PRs mentioned in the description that establish the pattern

### Step 2 — Spawn parallel review agents

Spawn one agent per selected lens **in the same turn** (parallel). Each agent:
- Reads its lens reference file (see `references/` below)
- Reads the relevant AGENTS.md files from the repo CWD (see below)
- Reads the changed source files directly from the local checkout
- Returns a structured list of findings

Pass each agent:
1. The PR's file list (from step 1)
2. The PR description / purpose
3. The base branch (e.g. `4.0`) so it can compare patterns
4. The path to its lens reference file
5. Which AGENTS.md files to read (see below)

**AGENTS.md files to give each agent** (paths relative to the repo root):
- `AGENTS.architecture-rules.md` — layering, import rules, concurrency rules
- `AGENTS.core-domain-rules.md` — DDD glossary, lifecycle, watcher patterns
- `AGENTS.md` — unit test conventions, build instructions, formatting rules

**Lens reference files** (relative to this skill):

| Lens | Reference file |
|------|---------------|
| L1   | `references/lens-architecture.md` |
| L2   | `references/lens-go-idioms.md` |
| L3   | `references/lens-juju-style.md` |
| L4   | `references/lens-test-coverage.md` |
| L5   | `references/lens-db-perf.md` |
| L6   | `references/lens-concurrency.md` |

Each reference file contains the focused checklist and agent prompt for that
lens. Read it before composing the subagent prompt.

### Step 3 — Verification pass

After all agents return, scan their findings for items marked Critical or
Major. For each one, do a targeted code read to confirm:

- The file and line actually contain what the agent claims
- The finding is a real issue, not a false positive from misreading context
- Overlapping findings from different agents refer to the same issue

Contested or uncertain findings should be downgraded to Minor or annotated
"unconfirmed" if you can't verify them. This step catches hallucinations and
context misreads before they end up in the final report.

### Step 4 — Merge and normalize

1. **Deduplicate** — if multiple agents flagged the same code location, merge
   into one finding, crediting all lenses that caught it.
2. **Normalize severity** — use the scale below; when agents disagree on
   severity, prefer the more conservative (higher) assessment after verification.
3. **Separate positives** — collect "what the PR does well" notes from all
   agents into their own section.

**Severity scale:**

| Level | Meaning |
|-------|---------|
| Critical | Correctness bug, data loss, or security issue — must fix before merge |
| Major | Significant gap that should be fixed before merge (missing safety test, sqlair style violation, important pattern inconsistency) |
| Minor | Nit or convention violation that should be fixed but won't block merge |
| Info | Observation worth noting; no action required |

### Step 5 — Write the report

Save the report to `$JUJU_REVIEW_REPORTS/pr-<N>-review.md`.
Use the template below exactly.

---

## Report Template

```markdown
# PR #XXXXX Review Report

**Title:** <title>
**Author:** <author>
**Base branch:** <base>
**Changes:** +<additions> / -<deletions> across <N> files
**Date reviewed:** <YYYY-MM-DD>
**Lenses applied:** <L1, L2, L3 ...>

---

## Executive Summary

<Two to four sentences: what the PR does, whether the approach is sound,
and the overall verdict. E.g. "LGTM with requested changes" or
"Needs rework before merge".>

---

## Architecture Alignment

<Only include if L1 was run. A table of key architectural checks with PASS/FAIL.>

| Check | Result |
|-------|--------|
| ...   | PASS   |

---

## Findings

### Critical

---

#### C1 — <Short title>

**File:** `path/to/file.go:line`
**Severity:** Critical

<Explanation. Quote the relevant code snippet. State why it's a problem
and suggest a fix.>

---

### Major

(same structure as Critical)

---

### Minor

(same structure)

---

### Informational

(same structure, but lighter — one paragraph each is fine)

---

## What the PR Does Well

- <Positive finding>
- <Positive finding>

---

## Finding Summary

| ID | File | Line | Severity | Topic |
|----|------|------|----------|-------|
| C1 | `file.go` | 42 | Critical | ... |
| M1 | `file.go` | 99 | Major | ... |
```
