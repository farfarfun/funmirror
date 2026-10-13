"""Sync between two hosting platforms: single repo or whole org."""

from funmirror.sync.platforms import (
    GitCodePlatform,
    GiteePlatform,
    GitHubPlatform,
    GitLabPlatform,
    Platform,
    Release,
    ReleaseAsset,
    ReleasesUnsupported,
    RepoRef,
    make_platform,
)
from funmirror.sync.release_sync import ReleaseSyncSummary, sync_releases
from funmirror.sync.repo_sync import DetectResult, SyncContext, SyncResult, detect_repo, sync_repo
from funmirror.sync.org_sync import sync_org

__all__ = [
    "Platform",
    "RepoRef",
    "Release",
    "ReleaseAsset",
    "ReleasesUnsupported",
    "GitHubPlatform",
    "GiteePlatform",
    "GitLabPlatform",
    "GitCodePlatform",
    "make_platform",
    "SyncContext",
    "SyncResult",
    "DetectResult",
    "ReleaseSyncSummary",
    "detect_repo",
    "sync_repo",
    "sync_releases",
    "sync_org",
]
