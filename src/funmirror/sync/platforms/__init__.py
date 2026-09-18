"""Hosting platforms funmirror can sync between: one module per platform."""

from funmirror.sync.platforms.base import Platform, RepoRef
from funmirror.sync.platforms.github import GitHubPlatform
from funmirror.sync.platforms.gitee import GiteePlatform, GiteeRepoExistsError

__all__ = [
    "Platform",
    "RepoRef",
    "GitHubPlatform",
    "GiteePlatform",
    "GiteeRepoExistsError",
]
