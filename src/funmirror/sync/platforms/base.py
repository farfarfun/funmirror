"""Base abstraction for a git hosting platform (GitHub, Gitee, ...)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class RepoRef:
    name: str
    default_branch: str = "master"


class Platform(ABC):
    """One hosting platform's repo/branch/clone capabilities.

    Each platform owns its own auth, HTTP session, and quirks (rate limits,
    WAFs, ...); callers only ever go through this interface so sync logic
    stays platform-agnostic.
    """

    name: str

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
