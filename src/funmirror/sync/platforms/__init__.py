"""Hosting platforms funmirror can sync between: one module per platform."""

from funmirror.sync.platforms.base import Platform, RepoRef
from funmirror.sync.platforms.github import GitHubPlatform
from funmirror.sync.platforms.gitee import GiteePlatform, GiteeRepoExistsError
from funmirror.sync.platforms.gitlab import GitLabPlatform
from funmirror.sync.platforms.gitcode import GitCodePlatform

__all__ = [
    "Platform",
    "RepoRef",
    "GitHubPlatform",
    "GiteePlatform",
    "GiteeRepoExistsError",
    "GitLabPlatform",
    "GitCodePlatform",
    "make_platform",
]


def make_platform(
    kind: str, *, token: str = "", key_file: str = "", endpoint: str = ""
) -> Platform:
    """Construct a Platform by name, e.g. "github", "gitee", "gitlab", "gitcode"."""
    if kind == "github":
        return GitHubPlatform(token=token)
    if kind == "gitee":
        if not key_file:
            raise ValueError(
                "gitee requires a --src-key-file/--dst-key-file (SSH key for push)"
            )
        return GiteePlatform(token=token, ssh_key_file=key_file)
    if kind == "gitlab":
        return GitLabPlatform(token=token, endpoint=endpoint or "gitlab.com")
    if kind == "gitcode":
        return GitCodePlatform(token=token)
    raise ValueError(f"unknown platform: {kind!r}")
