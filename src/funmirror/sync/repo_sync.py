"""Single-repo sync between two platforms: skip-if-unchanged check, then clone + push."""

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from farlog import get_logger

from funmirror.sync.platforms.base import Platform, RepoRef
from funmirror.sync.release_sync import sync_releases

logger = get_logger("funmirror")


@dataclass
class SyncContext:
    src: Platform
    dst: Platform
    force: bool = True
    sync_releases: bool = False
    release_limit: int = 0
    workdir: str = field(default_factory=lambda: tempfile.mkdtemp(prefix="funmirror-"))


@dataclass
class SyncResult:
    repo: str
    status: str  # "mirrored" | "skipped" | "failed"
    detail: str = ""
    src_sha: Optional[str] = None  # known-good src sha, for state-file bookkeeping
    dst_sha: Optional[str] = None  # known-good dst sha, for state-file bookkeeping


@dataclass
class DetectResult:
    """Phase-1 (detect) outcome for one repo.

    `outcome == "terminal"`: nothing more to do, `result` is final (skipped or
    failed). `outcome == "sync"`: the repo needs work in phase 2, carrying the
    already-confirmed `src_sha` forward so phase 2 doesn't have to re-query it.

    `git_up_to_date` means phase 1 proved the refs already match, but the repo
    was handed to phase 2 anyway because releases still need checking. Phase 2
    then skips the clone+push entirely.
    """

    repo: RepoRef
    outcome: str  # "terminal" | "sync"
    result: Optional[SyncResult] = None
    src_sha: Optional[str] = None
    git_up_to_date: bool = False


def _run(
    cmd: List[str], *, cwd: Optional[str] = None, env: Optional[Dict[str, str]] = None
):
    return subprocess.run(
        cmd, cwd=cwd, env=env, check=True, capture_output=True, text=True
    )


def _retry(fn, *args, attempts: int = 3, delay: float = 5, **kwargs):
    last_exc: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < attempts - 1:
                logger.warning(f"retry {attempt + 1}/{attempts} after error: {exc}")
                time.sleep(delay * (2**attempt))
    raise last_exc


def detect_repo(
    repo: RepoRef,
    src_org: str,
    dst_org: str,
    ctx: SyncContext,
    *,
    state_entry: Optional[Dict[str, str]] = None,
    incremental: bool = False,
) -> DetectResult:
    """Phase 1: cheap, read-only check for whether `repo` needs a real sync.

    Incremental: only the src commit sha is ever queried. If it still matches
    `state_entry["src_sha"]`, the repo is trusted unchanged (dst is never
    touched). Otherwise it's handed straight to phase 2 -- no dst read here
    either, since a changed src always implies a stale dst under this
    scheme's bookkeeping.

    Full (non-incremental): both src and dst commit shas are queried (state
    is ignored for the decision, though phase 2's confirmed results still
    refresh it), and only repos where they differ need a real sync.

    Either way, `ctx.sync_releases` turns every "up to date" verdict into a
    phase-2 handoff flagged `git_up_to_date`. Publishing a release moves a
    tag, not the default branch, so a repo whose branch sha is unchanged can
    still be missing its newest release -- skipping it on the branch sha
    alone would make release mirroring quietly miss exactly the case it
    exists for.
    """
    name = repo.name
    branch = repo.default_branch or "master"

    def up_to_date(src_sha, dst_sha, reason: str) -> DetectResult:
        if ctx.sync_releases:
            return DetectResult(repo, "sync", src_sha=src_sha, git_up_to_date=True)
        return DetectResult(
            repo, "terminal", SyncResult(name, "skipped", reason, src_sha, dst_sha)
        )

    try:
        src_sha = ctx.src.branch_sha(src_org, name, branch)

        if incremental:
            if state_entry and src_sha and src_sha == state_entry.get("src_sha"):
                return up_to_date(
                    src_sha,
                    state_entry.get("dst_sha"),
                    "unchanged since last sync (incremental)",
                )
            return DetectResult(repo, "sync", src_sha=src_sha)

        dst_sha = ctx.dst.branch_sha(dst_org, name, branch)
        if src_sha and src_sha == dst_sha:
            return up_to_date(src_sha, dst_sha, "up to date")
        return DetectResult(repo, "sync", src_sha=src_sha)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"{name}: detect failed: {exc}")
        return DetectResult(repo, "terminal", SyncResult(name, "failed", str(exc)))


def sync_repo(
    repo: RepoRef,
    src_org: str,
    dst_org: str,
    ctx: SyncContext,
    src_sha: Optional[str],
    git_up_to_date: bool = False,
) -> SyncResult:
    """Phase 2: make dst/repo exist, clone+push if it needs it, then releases."""
    name = repo.name
    try:
        if git_up_to_date:
            result = SyncResult(name, "skipped", "up to date", src_sha, src_sha)
        else:
            ctx.dst.ensure_repo(dst_org, name)
            result = _clone_and_push(name, src_org, dst_org, ctx)
            result.src_sha = src_sha
            if result.status == "mirrored":
                result.dst_sha = src_sha
    except Exception as exc:  # noqa: BLE001
        logger.error(f"{name}: sync failed: {exc}")
        return SyncResult(name, "failed", str(exc))

    if not ctx.sync_releases or result.status == "failed":
        return result

    # Strictly after the push: a Gitee release needs its tag to already be
    # there, otherwise it gets created against the wrong commit.
    try:
        released = sync_releases(
            name,
            src_org,
            dst_org,
            ctx.src,
            ctx.dst,
            limit=ctx.release_limit,
            workdir=ctx.workdir,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"{name}: release sync failed: {exc}")
        # Deliberately not recording state: the next run must retry this.
        return SyncResult(name, "failed", f"releases: {exc}")

    if released:
        result.status = "mirrored"
        result.detail = (
            f"{result.detail}, {released.describe()}"
            if result.detail and result.detail != "up to date"
            else released.describe()
        )
    return result


def _clone_and_push(
    name: str, src_org: str, dst_org: str, ctx: SyncContext
) -> SyncResult:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.update(ctx.src.git_env())
    env.update(ctx.dst.git_env())

    repo_dir = os.path.join(ctx.workdir, name)
    shutil.rmtree(repo_dir, ignore_errors=True)
    try:
        _retry(
            _run,
            ["git", "clone", "--quiet", ctx.src.clone_url(src_org, name), repo_dir],
            env=env,
        )
        _run(["git", "remote", "set-head", "origin", "-d"], cwd=repo_dir, env=env)

        rev = _run(
            ["git", "rev-list", "-n", "1", "--all"], cwd=repo_dir, env=env
        ).stdout.strip()
        if not rev:
            return SyncResult(name, "skipped", "empty repo")

        dst_url = ctx.dst.push_url(dst_org, name)
        _run(["git", "remote", "add", "dst", dst_url], cwd=repo_dir, env=env)
        push_cmd = [
            "git",
            "push",
            "dst",
            "refs/remotes/origin/*:refs/heads/*",
            "--tags",
            "--prune",
        ]
        if ctx.force:
            push_cmd.append("-f")
        _retry(_run, push_cmd, cwd=repo_dir, env=env)
        return SyncResult(name, "mirrored")
    finally:
        shutil.rmtree(repo_dir, ignore_errors=True)
