"""funmirror CLI: mirror repos between two hosting platforms."""

from __future__ import annotations

import json
import os
from typing import Optional

import typer
from farlog import get_logger

from funmirror.sync import SyncContext, make_platform, sync_org

logger = get_logger("funmirror")

PLATFORMS = ["github", "gitee", "gitlab", "gitcode"]


def _split_names(value: str) -> list[str]:
    return [n.strip() for n in value.split(",") if n.strip()]


def _state_namespace(
    src_platform: str, src_org: str, dst_platform: str, dst_org: str
) -> str:
    """A state file may be shared across multiple src/dst platform pairs (e.g.
    mirroring the same org to both Gitee and GitLab); namespace each pair's
    entries so one pair's progress can never be mistaken for another's."""
    return f"{src_platform}/{src_org}::{dst_platform}/{dst_org}"


def _load_state(path: str, namespace: str) -> dict[str, dict[str, str]]:
    if not path or not os.path.exists(path):
        return {}
    with open(path) as f:
        data = json.load(f)
    ns = data.get(namespace, {})
    return ns if isinstance(ns, dict) else {}


def _save_state(
    path: str, namespace: str, updates: dict[str, dict[str, str]]
) -> None:
    if not path:
        return
    data: dict[str, dict[str, dict[str, str]]] = {}
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


def _mirror(
    src_platform: str,
    dst_platform: str,
    src_org: str,
    dst_org: str,
    src_token: str = "",
    dst_token: str = "",
    src_key_file: str = "",
    dst_key_file: str = "",
    src_endpoint: str = "",
    dst_endpoint: str = "",
    repo_names: str = "",
    workers: int = 8,
    detect_workers: Optional[int] = None,
    force: bool = True,
    state_file: str = "",
    incremental: bool = False,
) -> int:
    src = make_platform(
        src_platform,
        token=src_token,
        key_file=src_key_file,
        endpoint=src_endpoint,
    )
    dst = make_platform(
        dst_platform,
        token=dst_token,
        key_file=dst_key_file,
        endpoint=dst_endpoint,
    )
    ctx = SyncContext(src=src, dst=dst, force=force)
    namespace = _state_namespace(src_platform, src_org, dst_platform, dst_org)
    state = _load_state(state_file, namespace)

    consumer = sync_org(
        ctx,
        src_org,
        dst_org,
        repo_names=_split_names(repo_names) or None,
        num_workers=workers,
        num_detect_workers=detect_workers,
        state=state,
        incremental=incremental,
    )
    _save_state(state_file, namespace, consumer.state_updates)

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


app = typer.Typer(help="Mirror repos between two hosting platforms")


@app.callback()
def main() -> None:
    """Mirror repos between two hosting platforms."""


def _platform(value: str) -> str:
    if value not in PLATFORMS:
        raise typer.BadParameter(f"must be one of: {', '.join(PLATFORMS)}")
    return value


@app.command(help="mirror a source org's repos to a destination org")
def mirror(
    src_platform: str = typer.Option(..., "--src-platform", callback=_platform),
    dst_platform: str = typer.Option(..., "--dst-platform", callback=_platform),
    src_org: str = typer.Option(..., "--src-org"),
    dst_org: str = typer.Option(..., "--dst-org"),
    src_token: str = typer.Option("", "--src-token"),
    dst_token: str = typer.Option("", "--dst-token"),
    src_key_file: str = typer.Option(
        "", "--src-key-file", help="SSH key file, only required for gitee"
    ),
    dst_key_file: str = typer.Option(
        "", "--dst-key-file", help="SSH key file, only required for gitee"
    ),
    src_endpoint: str = typer.Option(
        "", "--src-endpoint", help="self-hosted endpoint, only used for gitlab"
    ),
    dst_endpoint: str = typer.Option(
        "", "--dst-endpoint", help="self-hosted endpoint, only used for gitlab"
    ),
    repo_names: str = typer.Option(
        "", "--repo-names", help="comma-separated; empty means all repos"
    ),
    workers: int = typer.Option(8, "--workers"),
    detect_workers: Optional[int] = typer.Option(
        None,
        "--detect-workers",
        help=(
            "concurrency for the read-only commit-id detection phase; defaults "
            "to max(workers*4, 16)"
        ),
    ),
    force: bool = typer.Option(True, "--force/--no-force"),
    state_file: str = typer.Option(
        "",
        "--state-file",
        help="path to a JSON file that stores confirmed repository sync state",
    ),
    incremental: bool = typer.Option(
        False,
        "--incremental",
        help="skip destination checks when the source sha matches --state-file",
    ),
) -> None:
    try:
        exit_code = _mirror(
            src_platform=src_platform,
            dst_platform=dst_platform,
            src_org=src_org,
            dst_org=dst_org,
            src_token=src_token,
            dst_token=dst_token,
            src_key_file=src_key_file,
            dst_key_file=dst_key_file,
            src_endpoint=src_endpoint,
            dst_endpoint=dst_endpoint,
            repo_names=repo_names,
            workers=workers,
            detect_workers=detect_workers,
            force=force,
            state_file=state_file,
            incremental=incremental,
        )
    except KeyboardInterrupt:
        logger.warning("Interrupted")
        raise typer.Exit(1)
    except Exception:
        logger.exception("funmirror failed")
        raise typer.Exit(1)
    if exit_code:
        raise typer.Exit(exit_code)


def funmirror() -> None:
    app()


if __name__ == "__main__":
    funmirror()
