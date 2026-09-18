"""funmirror CLI: mirror a GitHub org to a Gitee org."""

import argparse
import os
import sys
from typing import List

from farlog import get_logger

from funmirror import platforms
from funmirror.mirror import MirrorContext
from funmirror.pipeline import run_mirror

logger = get_logger("funmirror")


def _split_names(value: str) -> List[str]:
    return [n.strip() for n in value.split(",") if n.strip()]


def _build_repo_list(args: argparse.Namespace) -> List[dict]:
    if args.repo_names:
        names = _split_names(args.repo_names)
        return [
            {
                "name": name,
                "default_branch": platforms.github_default_branch(
                    args.github_org, name, args.github_token
                )
                or "master",
            }
            for name in names
        ]
    return platforms.list_github_repos(args.github_org, args.github_token)


def _mirror(args: argparse.Namespace) -> int:
    repos = _build_repo_list(args)
    if not repos:
        logger.warning("No repos to mirror")
        return 0

    ctx = MirrorContext(
        github_org=args.github_org,
        gitee_org=args.gitee_org,
        gitee_token=args.gitee_token,
        gitee_key_file=args.gitee_key_file,
        github_token=args.github_token,
        force=args.force,
    )

    consumer = run_mirror(repos, ctx, num_workers=args.workers)

    summary = (
        f"Mirrored {len(consumer.mirrored)}, skipped {len(consumer.skipped)}, "
        f"failed {len(consumer.failed)} (total {len(repos)})"
    )
    logger.info(summary)

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a") as f:
            f.write(summary + "\n")

    if consumer.failed:
        logger.error(f"Failed: {', '.join(consumer.failed)}")
        return 1
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="funmirror", description="Mirror GitHub org repos to Gitee")
    commands = parser.add_subparsers(dest="command", required=True)

    mirror = commands.add_parser("mirror", help="mirror a GitHub org's repos to a Gitee org")
    mirror.add_argument("--github-org", required=True)
    mirror.add_argument("--gitee-org", required=True)
    mirror.add_argument("--gitee-token", required=True)
    mirror.add_argument("--gitee-key-file", required=True)
    mirror.add_argument("--github-token", default="")
    mirror.add_argument("--repo-names", default="", help="comma-separated; empty means all repos")
    mirror.add_argument("--workers", type=int, default=8)
    mirror.add_argument("--force", dest="force", action="store_true", default=True)
    mirror.add_argument("--no-force", dest="force", action="store_false")
    mirror.set_defaults(handler=_mirror)

    return parser


def funmirror() -> int:
    args = _parser().parse_args()
    try:
        return args.handler(args)
    except KeyboardInterrupt:
        logger.warning("Interrupted")
        return 1
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"funmirror failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(funmirror())
