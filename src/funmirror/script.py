"""funmirror CLI: mirror repos between two hosting platforms."""

import argparse
import json
import os
import sys
from typing import Dict, List

from farlog import get_logger

from funmirror.sync import SyncContext, make_platform, sync_org

logger = get_logger("funmirror")

PLATFORMS = ["github", "gitee", "gitlab", "gitcode"]


def _split_names(value: str) -> List[str]:
    return [n.strip() for n in value.split(",") if n.strip()]


def _load_state(path: str) -> Dict[str, str]:
    if not path or not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def _save_state(path: str, state: Dict[str, str], updates: Dict[str, str]) -> None:
    if not path:
        return
    merged = {**state, **updates}
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(merged, f, indent=2, sort_keys=True)
        f.write("\n")


def _mirror(args: argparse.Namespace) -> int:
    src = make_platform(
        args.src_platform,
        token=args.src_token,
        key_file=args.src_key_file,
        endpoint=args.src_endpoint,
    )
    dst = make_platform(
        args.dst_platform,
        token=args.dst_token,
        key_file=args.dst_key_file,
        endpoint=args.dst_endpoint,
    )
    ctx = SyncContext(src=src, dst=dst, force=args.force)
    state = _load_state(args.state_file)

    consumer = sync_org(
        ctx,
        args.src_org,
        args.dst_org,
        repo_names=_split_names(args.repo_names) or None,
        num_workers=args.workers,
        state=state,
        incremental=args.incremental,
    )
    _save_state(args.state_file, state, consumer.state_updates)

    total = consumer.total
    summary = (
        f"Mirrored {len(consumer.mirrored)}, skipped {len(consumer.skipped)}, "
        f"failed {len(consumer.failed)} (total {total})"
    )
    logger.info(summary)

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a") as f:
            f.write(summary + "\n")

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"mirrored={len(consumer.mirrored)}\n")
            f.write(f"skipped={len(consumer.skipped)}\n")
            f.write(f"failed={len(consumer.failed)}\n")
            f.write(f"total={total}\n")

    if consumer.failed:
        logger.error(f"Failed: {', '.join(consumer.failed)}")
        return 1
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="funmirror", description="Mirror repos between two hosting platforms"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    mirror = commands.add_parser(
        "mirror", help="mirror a source org's repos to a destination org"
    )
    mirror.add_argument("--src-platform", required=True, choices=PLATFORMS)
    mirror.add_argument("--dst-platform", required=True, choices=PLATFORMS)
    mirror.add_argument("--src-org", required=True)
    mirror.add_argument("--dst-org", required=True)
    mirror.add_argument("--src-token", default="")
    mirror.add_argument("--dst-token", default="")
    mirror.add_argument(
        "--src-key-file", default="", help="SSH key file, only required for gitee"
    )
    mirror.add_argument(
        "--dst-key-file", default="", help="SSH key file, only required for gitee"
    )
    mirror.add_argument(
        "--src-endpoint", default="", help="self-hosted endpoint, only used for gitlab"
    )
    mirror.add_argument(
        "--dst-endpoint", default="", help="self-hosted endpoint, only used for gitlab"
    )
    mirror.add_argument(
        "--repo-names", default="", help="comma-separated; empty means all repos"
    )
    mirror.add_argument("--workers", type=int, default=8)
    mirror.add_argument("--force", dest="force", action="store_true", default=True)
    mirror.add_argument("--no-force", dest="force", action="store_false")
    mirror.add_argument(
        "--state-file",
        default="",
        help=(
            "path to a JSON file mapping repo name -> last-synced src branch sha; "
            "read at start and rewritten at the end with every processed repo's "
            "confirmed sha. Empty disables state tracking."
        ),
    )
    mirror.add_argument(
        "--incremental",
        action="store_true",
        default=False,
        help=(
            "skip repos whose current src sha still matches --state-file, without "
            "ever querying the destination platform. Without this flag, every repo "
            "is checked against the destination as usual (full sync), and the "
            "state file (if given) is still refreshed from the confirmed results."
        ),
    )
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
