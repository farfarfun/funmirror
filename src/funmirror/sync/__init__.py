"""Sync between two hosting platforms: single repo or whole org."""

from funmirror.sync.platforms import (
    GitCodePlatform,
    GiteePlatform,
    GitHubPlatform,
    GitLabPlatform,
    Platform,
    RepoRef,
    make_platform,
)
from funmirror.sync.repo_sync import SyncContext, SyncResult, sync_repo
from funmirror.sync.org_sync import sync_org

__all__ = [
    "Platform",
    "RepoRef",
    "GitHubPlatform",
    "GiteePlatform",
    "GitLabPlatform",
    "GitCodePlatform",
    "make_platform",
    "SyncContext",
    "SyncResult",
    "sync_repo",
    "sync_org",
]
