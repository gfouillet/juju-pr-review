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

## Hard Rules

- `gh` is allowed for reads and for posting **pending** review comments only.
  Never use `gh` to submit (approve/request-changes), merge, change labels,
  push branches, or dismiss reviews.
- Posting comments as a PENDING review is allowed when the user explicitly
  requests it. Never submit a review — always leave it as PENDING for the
  user to review and submit from the GitHub UI.
- All QA execution must be local: LXD or MicroK8s only.
- Never bootstrap on a public cloud. If the PR template contains cloud-specific
  QA steps, skip them and report the skip explicitly.
- Do not claim QA passed if any required local step was skipped, failed, or
  left ambiguous.
- If cleanup fails, report that as a finding.

## Input Contract

- Expected input: a GitHub PR URL, a PR number, or — if no argument is given —
  the current branch.
- If the input is a URL, parse it with
  [`scripts/parse_pr_url.py`](./scripts/parse_pr_url.py) to extract `owner`,
  `repo`, and `pr_number`.
- If no PR number was given, try the current branch: run `gh pr view` without
  a number and let `gh` infer it.
- If `gh` can't find a PR, fall back to reading `git log --oneline -5` and
  `git diff --name-only origin/HEAD...HEAD` to understand what changed.
- If the repository is not available locally, say so and either locate another
  local checkout that matches the PR repository or ask before doing any
  networked read-only fetch or clone.
- **Missing or vague PR description is a finding.** If the PR description is
  missing, vague, or does not explain the problem being solved, flag it
  explicitly in the review.

### Self-review mode

After fetching PR metadata, detect whether the PR is authored by the user
running the skill:

```sh
gh api user --jq .login
```

If the PR author's login matches — i.e. **the PR is the reviewer's own work —
switch to self-review mode**:
- The review is never pushed to GitHub: skip Steps 5.5 and 6 entirely —
  no batch decision table, no pending review, no comment drafting.
- Still run the full lens review and write the report (Step 5).
- **Run the red-team pass (Step 5.1) before handing over.** Self-review has
  a systematic blind spot: it validates the author's own design choices
  instead of challenging them (e.g. PR #23701's report listed the
  report-only CI step under "What the PR Does Well"; an external bot later
  flagged the same mechanism as "the lint never gates anything"). The
  red-team pass exists to break that loop.
- Then hand the report over for triage: tell the user the report path and
  that they can prepare mitigations with the `check-review` skill —
  through a `/check-review <path-to-report>` command if their harness
  defines one, or by simply asking the agent to triage the report with
  the skill. Make sure the report's Finding Summary table is complete —
  it is what check-review consumes. Mitigations are folded into the
  existing commits (amend, or fixup + autosquash), never added as new
  commits.

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

Eight lenses are available. L1+L2+L3 are always active. L4–L8 are suggested
based on the PR file list — present the suggestion as a single question and
wait for the user to confirm or adjust.

| ID | Lens | Focus | Default |
|----|------|-------|:-------:|
| L1 | Architecture alignment | Layer boundaries, import rules, transaction scope, adjacent code path impact | on |
| L2 | Go idioms | Error handling, naming, interfaces, context, godoc | on |
| L3 | Juju style & idioms | sqlair patterns, DDD conventions, test structure, gci | on |
| L4 | Test coverage | Edge cases, missing scenarios, stress candidates, tool-contract violations | suggested |
| L5 | Database & performance | N+1 queries, bulk ops, chunking, transaction scope | suggested |
| L6 | Synchronization & concurrency | Channel lifecycle, goroutine safety, worker shutdown, race conditions | suggested |
| L7 | QA execution | Local LXD/MicroK8s validation, build, controller lifecycle | suggested |
| L8 | CI & build wiring | Workflow gating, guard conditions on non-PR events, action pinning, Makefile hygiene, fail-loud environment drift | suggested |

### Suggestion rules

After gathering the file list in Step 1, suggest additional lenses based on
the changed files:

| Condition | Suggest |
|-----------|------|
| Any `*_test.go` file in the diff | L4 |
| Any file under `domain/*/state/`, `domain/*/service/`, or containing SQL/sqlair queries | L5 |
| Any file under `worker/`, `internal/worker/`, or using channels/goroutines | L6 |
| PR description contains QA steps or mentions LXD/MicroK8s | L7 |
| Any file under `.github/workflows/`, any `Makefile`/`*.mk` change, or the PR adds/modifies a CI job, lint target, or version pin | L8 |

Present the suggested set as a **single question** — not one question per
lens, and not a statement that proceeds without asking. Always remind the
user of each lens's actual scope: spell out the lens name and focus next
to its number — never refer to lenses by number alone, including the
always-on set:

> "L1+L2+L3 active (L1 architecture alignment — layer boundaries, import
> rules, transaction scope; L2 Go idioms — error handling, naming, godoc;
> L3 Juju style & idioms — sqlair patterns, DDD conventions, test
> structure). Suggesting L4 (test coverage — edge cases, missing
> scenarios) + L5 (database & performance — N+1 queries, transaction
> scope) based on the PR content (test files, DB service code). Add L6
> (synchronization & concurrency — channel lifecycle, goroutine safety,
> race conditions) and/or L7 (QA execution — local LXD/MicroK8s
> validation, controller lifecycle)?"
>
> Options: Proceed with suggested | Add L6 | Add L7 | Add both

Wait for the user's answer, then proceed with the selected set.

When L7 is activated, **start it first** — QA is the longest-running step and
its results inform the rest of the review.

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

Also fetch any **existing reviews and review comments** on the PR — they
are input to the review, not just noise:

```sh
gh api repos/<owner>/<repo>/pulls/<pr>/reviews --jq '.[] | {id, user: .user.login, state, submitted_at, body}'
gh api repos/<owner>/<repo>/pulls/<pr>/comments --jq '.[] | {id, path, line, user: .user.login, body}'
```

Record what each prior review flagged or endorsed. When drafting
comments (Steps 5.5–6):
- Reference a related prior review or review comment in the comment's
  `<details>` context block instead of restating it.
- Do not post a finding that adds no value over an existing review
  comment — only post if you bring specific line context, clarity, or
  insight the prior comment lacks.

### Step 1.5 — Understand the change before judging it

Read the PR description, the diff, and the touched code paths together. Do not
spawn review agents until you can answer these questions:

- What is the **claimed problem** the PR says it solves?
- What is the **actual behavior being changed**?
- What is the **scope** of the fix — is it smaller or broader than necessary?
- Does the **implementation match the stated intent**?

If the PR description is missing, vague, or does not explain the problem, flag
it as a finding (see Input Contract). If there is a mismatch between the
description and what the code actually does, note it — it will be passed to
all subagents as context so they can verify alignment.

The output of this step is a short "change understanding" summary that is
included in every subagent prompt.

### Step 2 — Spawn parallel review agents

Spawn one agent per selected lens **in the same turn** (parallel). Each agent:
- Reads its lens reference file (see `references/` below)
- Reads the relevant AGENTS.md files from the repo CWD (see below)
- Reads the changed source files directly from the local checkout
- Returns a structured list of findings

Pass each agent:
1. The PR's file list (from step 1)
2. The PR description / purpose
3. The "change understanding" summary (from step 1.5)
4. The base branch (e.g. `4.0`) so it can compare patterns
5. The path to its lens reference file
6. Which AGENTS.md files to read (see below)

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
| L7   | `references/lens-qa.md` |
| L8   | `references/lens-ci-build.md` |

Each reference file contains the focused checklist and agent prompt for that
lens. Read it before composing the subagent prompt.

### Step 3 — Verification pass

After all agents return, scan their findings for items marked Critical or
Major. For each one, do a targeted code read to confirm:

- The file and line actually contain what the agent claims
- The finding is a real issue, not a false positive from misreading context
- Overlapping findings from different agents refer to the same issue

**Verify line numbers from the local checkout, NOT from GitHub API.** Run:

```sh
git diff origin/<base>...HEAD -- <file>
```

This gives the same diff hunk information without network calls. Match
finding line numbers against the diff hunks to confirm they point at the
right code.

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
4. **Check the lens-set severity ceiling** — the behavioural lenses are
   L1 (blast radius), L4 (invariants and edge cases), L5, L6, and L8 (CI
   gating and environment drift). The style lenses L2/L3 structurally top
   out at Minor: no idiom finding can be a correctness bug. If the active
   lens set is style-only, no Critical/Major finding is *possible*, so
   "no Critical or Major findings" is a statement about the lens set, not
   about the PR. In that case the report header and the final verdict must
   say so explicitly (see the report template) — an unqualified
   "approve-ready" from a style-only review overstates the result.
   (On PR #23701 a style-only self-review — L1/L4 omitted as "standalone
   tool" — returned "approve-ready" while a later external bot review found
   a correctness bug, a non-gating CI step, and a performance issue.)

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

### Step 5.1 — Red-team pass

**Mandatory in self-review mode** (see Input Contract); recommended for any
review where all findings landed at Minor or below.

After the report is written, run one adversarial step on it:

1. Adopt the persona of a skeptical external reviewer with 30 minutes and
   zero ego investment in the PR. Ask: what would they flag that this
   report does not? Think in failure modes, not in style:
   - What does this PR claim to enforce or guarantee, and where could that
     claim be silently false? (A check that cannot fail, a contract the
     code silently violates, a pin that only holds in CI.)
   - What would the harshest competent reviewer say about the design
     choices the report currently *praises*?
   - List at least 3 candidates — do not self-censor because the report
     already endorses the choice.
2. Verify each candidate against the code with the same rules as Step 3
   (targeted read of the actual files; downgrade or discard what does not
   hold up).
3. Fold confirmed items into the report with proper severity, and remove
   or soften any "What the PR Does Well" bullet the pass contradicted.

The pass is a behaviour change, not just new findings: a self-review report
must never present the author's own design choices as unqualified strengths
without at least having tried to break them.

### Step 5.5 — Batch decision for publishing

**Skip this step in self-review mode** (own PR — see Input Contract):
the report is handed to `/check-review` instead of being published.

After the report is saved, ask the user if they want to publish findings to
GitHub as a pending review. If yes, present **all** findings in a single table
and collect decisions in **one** round-trip — never iterate one finding at a
time.

Draft the comment bodies here following the Step 6 comment rules — concise by
default, context paragraph only when needed — so the preview column shows the
exact text that will be posted.

**Default actions and labels** (auto-assigned, user overrides in the table):

| Finding type | Default action | Default label |
|--------------|:--------------:|---------------|
| Critical | post | **issue** |
| Major | post | **todo** |
| Minor (style/convention) | post | **nitpick** |
| Minor (missing test) | post | **todo** |
| Minor (improvement suggestion) | post | **suggestion** |
| Minor — test mechanically updated by a refactor (no behavioural change) | post | **suggestion** |
| Info (observation/question) | skip | — |
| Info (positive note) | skip | — |

A test that was just mechanically refactored (renamed call, moved
helper) is not the right place to demand deeper behavioural assertions —
suggest, don't block; the behavioural gap belongs where the behaviour
lives (e.g. a state-layer test).

**Conventional Comment labels** ([conventionalcomments.org](https://conventionalcomments.org/)),
written as `type(scope)` in comment bodies — the scope in parentheses is
the area of concern (`test`, `diff`, `state`, `service`, `facade`, ...):

| Label | Meaning |
|-------|---------|
| `issue` | This is a bug or correctness problem that must be fixed |
| `todo` | Should be fixed before merge, no recheck needed |
| `nitpick` | Minor preference-based nitpick |
| `suggestion` | Suggesting a potential improvement |
| `question` | Asking a clarifying question |
| `thought` | Worth considering — sharing an idea |

Present the table as a single `question` call:

```
Here are all findings ready to post as a pending review on PR #<N>.
Review the table — tell me to "approve", or specify row edits (e.g. "M3: skip, M6: suggestion").

| ID | Sev | File:Line | Label | Action | Comment (preview) |
|----|------|-----------|-------|--------|---------------------|
| M1 | Minor | secretrewrite.go:33 | nitpick | post | The emptiness check uses == nil... |
| M2 | Minor | secretrewrite_test.go:22 | todo | post | Test function names use underscores... |
| ... | | | | | |
```

Options:
- **Approve — post all as shown**: Post all findings with their default labels
- **Edit specific rows**: Specify which rows to change (skip, relabel, amend text)

If the user says "approve" or "go", proceed to Step 6 immediately — no further
questions. If the user specifies edits, apply them and proceed.

**Never iterate findings one at a time.** The entire decision flow is a single
question with an optional follow-up for edits.

### Step 6 — Publish to GitHub

**Skip this step in self-review mode** (own PR — see Input Contract):
never push the review to GitHub; the report goes to `/check-review`.

Post the approved comments as a **pending** review on the PR using
[`scripts/post_review.py`](./scripts/post_review.py). This script handles the
GitHub API correctly — do not call `gh api` manually for review creation.

```sh
python3 scripts/post_review.py \
  --owner <owner> --repo <repo> --pr <number> \
  --comments <path/to/comments.json>
```

The comments JSON file format:

```json
{
  "commit_id": "<head sha>",
  "comments": [
    {
      "path": "internal/migration/secretrewrite.go",
      "line": 33,
      "body": "**nitpick(diff):** use `len(s) == 0` instead of `s == nil`.\n\n<details>\n<summary>AI sloppy context</summary>\n\nA non-nil empty map passes the `== nil` check, so the rewrite would be skipped.\n\n</details>"
    }
  ]
}
```

**Rules for comment bodies** (conventional comments + AI context block):
- Start each comment with the conventional label and an optional scope
  in bold: `**issue:**`, `**todo(test):**`, `**nitpick(diff):**`,
  `**suggestion(state):**`, etc. The type comes from the Step 5.5 label
  table; the scope in parentheses names the area of concern.
- After the label, one short, concise phrase focused on what we should
  do, what is expected, or an insight — a single sentence, no more.
- If there is useful context, follow with a collapsed block:

  ```
  <details>
  <summary>AI sloppy context</summary>

  <Structured context for easy reading: why it matters, other relevant
  pieces of code or files, what you suggest to do, references to prior
  review comments on this PR. Short paragraphs or bullet lists. Be as
  concise as possible.>
  </details>
  ```

  The details block supplements the one-phrase header; the first line
  must stand alone without it.
- Reference related prior reviews/review comments in the details block
  rather than restating them; skip posting when you add no specific
  line context, clarity, or insight over them.
- **Inline comments must anchor to files in the PR diff** — GitHub
  rejects comments on unchanged files. For findings outside the diff,
  put them in the review body instead (`--body`), stating the
  `File:Line` in the text.
- For multi-line comments, include `start_line` in the JSON (must be on
  the same side of the diff as `line`).

**Before posting:**
1. Get the head SHA: `gh api repos/<owner>/<repo>/pulls/<pr> --jq '.head.sha'`
2. Check for existing pending reviews: `gh api repos/<owner>/<repo>/pulls/<pr>/reviews --jq '.[] | select(.state=="PENDING") | {id, body}'`
3. If an existing pending review exists, ask the user whether to delete and
   recreate it (all comments will be in the new review).

**After posting:**
- Confirm the review URL to the user
- Clean up any temp JSON files

**Amending a posted pending review:**
- Review comments inside a pending review cannot be edited via the API
  (`PATCH` on the comment returns 404 — pending comments only exist
  within the review until submission). To change a comment, delete and
  recreate the whole pending review with `post_review.py --force`,
  applying the edits to the regenerated comments.

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
**Lens coverage:** <include ONLY when the active lens set is style-only
(L2/L3 without any of L1/L4/L5/L6/L8): state that no behavioural or
correctness dimension was reviewed, e.g. "style lenses only — no
behavioural lens was active; absence of Critical/Major findings reflects
the lens set, not the PR">

---

## Executive Summary

<Two to four sentences: what the PR does, whether the approach is sound,
and the overall verdict. E.g. "LGTM with requested changes" or
"Needs rework before merge".>

---

## QA

<Only include if L7 was run. Omit the section entirely if L7 was not activated.>

**Environment:** LXD | MicroK8s
**Steps run:** <count>
**Steps skipped:** <count> (list each with reason)
**Result:** passed | failed | partial | not run
**Evidence:**
  - <step description>: <pass/fail> — <key output or error>
  - ...
**Cleanup:** complete | failed (<error>)

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

## Open Questions

<Only include genuinely unresolved points that need the author's input. Omit
the section entirely if there are none.>

- <Question about an assumption the PR makes that is not confirmed by the code
  or tests>
- <Question about a design decision where the reviewer sees alternatives>

---

## Finding Summary

| ID | File | Line | Severity | Topic |
|----|------|------|----------|-------|
| C1 | `file.go` | 42 | Critical | ... |
| M1 | `file.go` | 99 | Major | ... |

---

## Final Verdict

**Verdict:** approve-ready | needs changes | blocked by missing clarity
**Justification:** <one sentence; if the active lens set was style-only, the
verdict MUST be qualified — e.g. "approve-ready for the dimensions
reviewed; no behavioural lens was active">
```
