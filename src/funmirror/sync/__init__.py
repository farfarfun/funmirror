"""Sync between two hosting platforms: single repo or whole org."""

from funmirror.sync.platforms import GitHubPlatform, GiteePlatform, Platform, RepoRef
from funmirror.sync.repo_sync import SyncContext, SyncResult, sync_repo
from funmirror.sync.org_sync import sync_org

__all__ = [
    "Platform",
    "RepoRef",
    "GitHubPlatform",
    "GiteePlatform",
    "SyncContext",
    "SyncResult",
    "sync_repo",
    "sync_org",
]
