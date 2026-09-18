"""Single-repo mirror logic: skip-if-unchanged check, then clone + push."""

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from farlog import get_logger

from funmirror import platforms

logger = get_logger("funmirror")


@dataclass
class MirrorContext:
    github_org: str
    gitee_org: str
    gitee_token: str
    gitee_key_file: str
    github_token: str = ""
    force: bool = True
    workdir: str = field(default_factory=lambda: tempfile.mkdtemp(prefix="funmirror-"))


@dataclass
class MirrorResult:
    repo: str
    status: str  # "mirrored" | "skipped" | "failed"
    detail: str = ""


def _git_env(ctx: MirrorContext) -> Dict[str, str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_SSH_COMMAND"] = (
        f"ssh -i {ctx.gitee_key_file} -o StrictHostKeyChecking=no -o IdentitiesOnly=yes"
    )
    return env


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


def mirror_one(repo: Dict, ctx: MirrorContext) -> MirrorResult:
    name = repo["name"]
    branch = repo.get("default_branch") or "master"

    try:
        src_sha = platforms.github_branch_sha(
            ctx.github_org, name, branch, ctx.github_token
        )

        if platforms.gitee_repo_exists(ctx.gitee_org, name, ctx.gitee_token):
            dst_sha = platforms.gitee_branch_sha(
                ctx.gitee_org, name, branch, ctx.gitee_token
            )
        else:
            logger.info(f"{name}: doesn't exist on Gitee, creating")
            platforms.gitee_create_repo(ctx.gitee_org, name, ctx.gitee_token)
            dst_sha = None

        if src_sha and src_sha == dst_sha:
            return MirrorResult(name, "skipped", "up to date")

        return _clone_and_push(name, ctx, env=_git_env(ctx))
    except Exception as exc:  # noqa: BLE001
        logger.error(f"{name}: mirror failed: {exc}")
        return MirrorResult(name, "failed", str(exc))


def _clone_and_push(
    name: str, ctx: MirrorContext, *, env: Dict[str, str]
) -> MirrorResult:
    repo_dir = os.path.join(ctx.workdir, name)
    shutil.rmtree(repo_dir, ignore_errors=True)
    try:
        src_url = f"https://github.com/{ctx.github_org}/{name}.git"
        if ctx.github_token:
            src_url = f"https://x-access-token:{ctx.github_token}@github.com/{ctx.github_org}/{name}.git"

        _retry(_run, ["git", "clone", "--quiet", src_url, repo_dir], env=env)
        _run(["git", "remote", "set-head", "origin", "-d"], cwd=repo_dir, env=env)

        rev = _run(
            ["git", "rev-list", "-n", "1", "--all"], cwd=repo_dir, env=env
        ).stdout.strip()
        if not rev:
            return MirrorResult(name, "skipped", "empty repo")

        dst_url = f"git@gitee.com:{ctx.gitee_org}/{name}.git"
        _run(["git", "remote", "add", "gitee", dst_url], cwd=repo_dir, env=env)
        push_cmd = [
            "git",
            "push",
            "gitee",
            "refs/remotes/origin/*:refs/heads/*",
            "--tags",
            "--prune",
        ]
        if ctx.force:
            push_cmd.append("-f")
        _retry(_run, push_cmd, cwd=repo_dir, env=env)
        return MirrorResult(name, "mirrored")
    finally:
        shutil.rmtree(repo_dir, ignore_errors=True)
