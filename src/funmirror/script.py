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


def _state_namespace(args: argparse.Namespace) -> str:
    """A state file may be shared across multiple src/dst platform pairs (e.g.
    mirroring the same org to both Gitee and GitLab); namespace each pair's
    entries so one pair's progress can never be mistaken for another's."""
    return f"{args.src_platform}/{args.src_org}::{args.dst_platform}/{args.dst_org}"


def _load_state(path: str, namespace: str) -> Dict[str, Dict[str, str]]:
    if not path or not os.path.exists(path):
        return {}
    with open(path) as f:
        data = json.load(f)
    ns = data.get(namespace, {})
    return ns if isinstance(ns, dict) else {}


def _save_state(
    path: str, namespace: str, updates: Dict[str, Dict[str, str]]
) -> None:
    if not path:
        return
    data: Dict[str, Dict[str, Dict[str, str]]] = {}
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
    ns = data.get(namespace)
    if not isinstance(ns, dict):
        ns = {}
    ns.update(updates)
    data[namespace] = ns
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
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
    namespace = _state_namespace(args)
    state = _load_state(args.state_file, namespace)

    consumer = sync_org(
        ctx,
        args.src_org,
        args.dst_org,
        repo_names=_split_names(args.repo_names) or None,
        num_workers=args.workers,
        num_detect_workers=args.detect_workers,
        state=state,
        incremental=args.incremental,
    )
    _save_state(args.state_file, namespace, consumer.state_updates)

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
    mirror.add_argument(
        "--detect-workers",
        type=int,
        default=None,
        help=(
            "concurrency for the read-only commit-id detection phase (runs before "
            "--workers' clone+push phase); defaults to max(workers*4, 16). Keep "
            "--workers low to protect a rate-limited destination while detection "
            "still runs fast, since it never touches git."
        ),
    )
    mirror.add_argument("--force", dest="force", action="store_true", default=True)
    mirror.add_argument("--no-force", dest="force", action="store_false")
    mirror.add_argument(
        "--state-file",
        default="",
        help=(
            "path to a JSON file (namespaced by src/dst platform+org, so one file "
            "can safely be shared across multiple pairs) mapping repo name -> "
            "{src_sha, dst_sha} last confirmed in sync; read at start and "
            "rewritten at the end with every processed repo's confirmed shas. "
            "Empty disables state tracking."
        ),
    )
    mirror.add_argument(
        "--incremental",
        action="store_true",
        default=False,
        help=(
            "only query the src platform's commit id; a repo whose src sha still "
            "matches --state-file is skipped entirely (dst is never queried). A "
            "repo whose src sha changed is sent straight to sync without a dst "
            "check either, trusting --state-file's bookkeeping that dst was in "
            "sync as of the last recorded src sha. Without this flag (full sync), "
            "every repo's dst is queried for real and compared directly against "
            "src, ignoring --state-file for the decision (though it's still "
            "refreshed from the confirmed results) -- use this periodically to "
            "self-heal any drift."
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
