#!/usr/bin/env python3
"""Parse a GitHub PR URL into owner, repo, and PR number.

Accepts formats:
  https://github.com/juju/juju/pull/22711
  https://github.com/juju/juju/pull/22711/files
  github.com/juju/juju/pull/22711
  juju/juju#22711

Usage:
  python3 parse_pr_url.py <url>
  python3 parse_pr_url.py <url> --format json

Output (default):
  owner=<owner>
  repo=<repo>
  pr_number=<number>

Exit codes:
  0 — success
  1 — could not parse
"""

import argparse
import json
import re
import sys


def parse_pr_url(url: str) -> dict | None:
    url = url.strip()

    # Full URL: https://github.com/owner/repo/pull/123[/...]
    m = re.match(
        r"(?:https?://)?github\.com/([^/]+)/([^/]+)/pull/(\d+)",
        url,
    )
    if m:
        return {
            "owner": m.group(1),
            "repo": m.group(2),
            "pr_number": int(m.group(3)),
        }

    # Shorthand: owner/repo#123
    m = re.match(r"^([^/\s]+)/([^/\s#]+)#(\d+)$", url)
    if m:
        return {
            "owner": m.group(1),
            "repo": m.group(2),
            "pr_number": int(m.group(3)),
        }

    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse a GitHub PR URL.")
    parser.add_argument("url", help="GitHub PR URL or shorthand")
    parser.add_argument(
        "--format",
        choices=["plain", "json"],
        default="plain",
        help="Output format (default: plain)",
    )
    args = parser.parse_args()

    result = parse_pr_url(args.url)
    if result is None:
        print(f"error: could not parse '{args.url}'", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(result))
    else:
        print(f"owner={result['owner']}")
        print(f"repo={result['repo']}")
        print(f"pr_number={result['pr_number']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
