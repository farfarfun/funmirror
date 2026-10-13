"""Base abstraction for a git hosting platform (GitHub, Gitee, ...)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class RepoRef:
    name: str
    default_branch: str = "master"


@dataclass
class ReleaseAsset:
    """One file attached to a release.

    `size` is -1 when the platform doesn't report it; callers must then fall
    back to matching on name alone rather than assuming a size of 0. `id` is
    the platform's own handle for the attachment, needed to delete it.
    """

    name: str
    size: int = -1
    download_url: str = ""
    id: str = ""


@dataclass
class Release:
    tag: str
    name: str = ""
    body: str = ""
    prerelease: bool = False
    target_commitish: str = ""
    assets: List[ReleaseAsset] = field(default_factory=list)


class ReleasesUnsupported(RuntimeError):
    """Raised when a platform is asked to do release work it doesn't implement."""


class Platform(ABC):
    """One hosting platform's repo/branch/clone capabilities.

    Each platform owns its own auth, HTTP session, and quirks (rate limits,
    WAFs, ...); callers only ever go through this interface so sync logic
    stays platform-agnostic.
    """

    name: str

    # Release mirroring is split in two because the two halves are wildly
    # different amounts of work: reading is a couple of GETs, writing means
    # creating releases and streaming file uploads. A platform may well be
    # usable as a release source long before anyone implements the write side.
    reads_releases: bool = False
    writes_releases: bool = False

    @abstractmethod
    def list_repos(self, org: str) -> List[RepoRef]:
        """List all repos in `org`, with their default branch."""

    @abstractmethod
    def default_branch(self, org: str, repo: str) -> Optional[str]:
        """The default branch name for org/repo, or None if it doesn't exist."""

    @abstractmethod
    def branch_sha(self, org: str, repo: str, branch: str) -> Optional[str]:
        """Latest commit sha of org/repo's `branch`, or None if missing."""

    @abstractmethod
    def ensure_repo(self, org: str, repo: str) -> None:
        """Idempotent: make sure org/repo exists on this platform, creating it if not."""

    @abstractmethod
    def clone_url(self, org: str, repo: str) -> str:
        """URL to clone org/repo from, with any auth this platform needs baked in."""

    @abstractmethod
    def push_url(self, org: str, repo: str) -> str:
        """URL to push org/repo to, with any auth this platform needs baked in."""

    def git_env(self) -> Dict[str, str]:
        """Extra environment variables git subprocesses need (e.g. an SSH key)."""
        return {}

    # --- release mirroring, source side -------------------------------------

    def list_releases(self, org: str, repo: str) -> List[Release]:
        """Published releases of org/repo, newest first. Drafts are excluded:
        a draft isn't public on the source, so mirroring it would leak it."""
        raise ReleasesUnsupported(f"{self.name} cannot read releases")

    def download_asset(self, asset: ReleaseAsset, dest_path: str) -> None:
        """Stream `asset` to `dest_path`. Streaming, not buffering: release
        assets are routinely hundreds of MB."""
        raise ReleasesUnsupported(f"{self.name} cannot read releases")

    # --- release mirroring, destination side --------------------------------

    def ensure_release(self, org: str, repo: str, release: Release) -> Tuple[str, bool]:
        """Idempotent: make sure a release for `release.tag` exists. Returns
        its platform-specific id (opaque to callers, fed back to the asset
        methods below) and whether this call is what created it."""
        raise ReleasesUnsupported(f"{self.name} cannot write releases")

    def release_assets(self, org: str, repo: str, release_id: str) -> List[ReleaseAsset]:
        """Files already attached to that release, for diffing against the source."""
        raise ReleasesUnsupported(f"{self.name} cannot write releases")

    def upload_asset(self, org: str, repo: str, release_id: str, path: str) -> None:
        """Attach the local file at `path` to that release."""
        raise ReleasesUnsupported(f"{self.name} cannot write releases")

    def delete_asset(self, org: str, repo: str, release_id: str, asset: ReleaseAsset) -> None:
        """Detach a previously uploaded file, so a changed one can replace it."""
        raise ReleasesUnsupported(f"{self.name} cannot write releases")
