#!/usr/bin/env python3
"""Post review comments as a PENDING review on a GitHub pull request.

This script wraps the GitHub REST API via `gh` CLI to create a pending review
with inline comments. It deliberately does NOT set the `event` field — the REST
API rejects "PENDING" as an event value. Omitting `event` entirely creates a
pending (unsubmitted) review that the user can review and submit from the
GitHub UI.

Usage:
    python3 post_review.py --owner juju --repo juju --pr 22783 --comments comments.json

The comments JSON file must have this shape:
    {
        "commit_id": "abc123...",
        "comments": [
            {
                "path": "internal/migration/secretrewrite.go",
                "line": 33,
                "body": "**nitpick:** The emptiness check uses == nil..."
            },
            {
                "path": "domain/secretbackend/service/import.go",
                "start_line": 85,
                "line": 89,
                "body": "**todo:** Duplicate revision UUID..."
            }
        ]
    }

Exit codes:
    0 — review posted successfully
    1 — usage error or missing prerequisites
    2 — GitHub API error
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def gh_api(*args: str) -> dict:
    """Call `gh api` and return parsed JSON output."""
    cmd = ["gh", "api", *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"error: gh api failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(2)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def get_head_sha(owner: str, repo: str, pr_number: int) -> str:
    """Get the head commit SHA of the PR."""
    data = gh_api(
        f"repos/{owner}/{repo}/pulls/{pr_number}",
        "--jq", ".head.sha",
    )
    if isinstance(data, str):
        return data.strip().strip('"')
    return data.get("sha", "")


def check_existing_pending(owner: str, repo: str, pr_number: int) -> list:
    """Check for existing pending reviews on the PR."""
    cmd = [
        "gh", "api",
        f"repos/{owner}/{repo}/pulls/{pr_number}/reviews",
        "--jq", "[.[] | select(.state==\"PENDING\") | {id: .id, body: .body}]",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return []
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


def delete_review(owner: str, repo: str, pr_number: int, review_id: int) -> bool:
    """Delete an existing pending review."""
    result = subprocess.run(
        ["gh", "api", "-X", "DELETE",
         f"repos/{owner}/{repo}/pulls/{pr_number}/reviews/{review_id}"],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def post_pending_review(
    owner: str,
    repo: str,
    pr_number: int,
    commit_id: str,
    comments: list,
    body: str | None = None,
) -> dict:
    """Post a pending review with inline comments.

    Key insight: the REST API rejects ``"event": "PENDING"`` (HTTP 422).
    Omitting the ``event`` field entirely creates a pending review.
    """
    payload: dict = {
        "commit_id": commit_id,
        "comments": comments,
    }
    if body:
        payload["body"] = body

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, dir="/tmp"
    ) as f:
        json.dump(payload, f, indent=2)
        tmp_path = f.name

    try:
        result = subprocess.run(
            ["gh", "api", "-X", "POST",
             f"repos/{owner}/{repo}/pulls/{pr_number}/reviews",
             "--input", tmp_path,
             "--jq", "{id: .id, state: .state, html_url: .html_url}"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"error: failed to post review: {result.stderr.strip()}", file=sys.stderr)
            sys.exit(2)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"raw_output": result.stdout}
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Post review comments as a pending GitHub review."
    )
    parser.add_argument("--owner", required=True, help="Repository owner")
    parser.add_argument("--repo", required=True, help="Repository name")
    parser.add_argument("--pr", type=int, required=True, help="PR number")
    parser.add_argument(
        "--comments", required=True,
        help="Path to JSON file with commit_id and comments array",
    )
    parser.add_argument(
        "--body", default=None,
        help="Optional top-level review body (Markdown)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Delete existing pending reviews without asking",
    )
    args = parser.parse_args()

    comments_path = Path(args.comments)
    if not comments_path.exists():
        print(f"error: comments file not found: {comments_path}", file=sys.stderr)
        return 1

    try:
        data = json.loads(comments_path.read_text())
    except json.JSONDecodeError as e:
        print(f"error: invalid JSON in comments file: {e}", file=sys.stderr)
        return 1

    commit_id = data.get("commit_id", "")
    comments = data.get("comments", [])

    if not comments:
        print("error: no comments in JSON file", file=sys.stderr)
        return 1

    if not commit_id:
        print("Fetching head SHA...", file=sys.stderr)
        commit_id = get_head_sha(args.owner, args.repo, args.pr)
        if not commit_id:
            print("error: could not determine head SHA", file=sys.stderr)
            return 2

    existing = check_existing_pending(args.owner, args.repo, args.pr)
    if existing:
        print(f"Found {len(existing)} existing pending review(s):", file=sys.stderr)
        for rev in existing:
            body_preview = (rev.get("body") or "")[:80]
            print(f"  ID {rev['id']}: body=\"{body_preview}\"", file=sys.stderr)

        if args.force:
            for rev in existing:
                print(f"Deleting review {rev['id']} (--force)...", file=sys.stderr)
                if not delete_review(args.owner, args.repo, args.pr, rev["id"]):
                    print(f"warning: could not delete review {rev['id']}", file=sys.stderr)
        else:
            print(
                "\nExisting pending review(s) found. Use --force to delete and "
                "recreate, or clear them manually from GitHub.\n"
                "Note: GitHub only allows one pending review per user per PR.",
                file=sys.stderr,
            )
            return 1

    print(f"Posting {len(comments)} comment(s) as pending review...", file=sys.stderr)
    result = post_pending_review(
        args.owner, args.repo, args.pr, commit_id, comments,
        body=args.body,
    )

    url = result.get("html_url", "")
    review_id = result.get("id", "")
    state = result.get("state", "")

    print(f"Review posted: {url}", file=sys.stderr)
    print(f"  ID: {review_id} | State: {state}", file=sys.stderr)
    print(f"\nReview URL: {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
