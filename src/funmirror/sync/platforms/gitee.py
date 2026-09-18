"""Gitee REST API platform."""

import threading
import time
from typing import Dict, List, Optional

import requests
from farlog import get_logger

from funmirror.sync.platforms.base import Platform, RepoRef

logger = get_logger("funmirror")

API = "https://gitee.com/api/v5"


class GiteeRepoExistsError(RuntimeError):
    """Raised when Gitee reports the destination repo already exists (idempotent create)."""


def _retry(fn, *args, attempts: int = 3, delay: float = 2, **kwargs):
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


class GiteePlatform(Platform):
    name = "gitee"

    def __init__(self, token: str, ssh_key_file: str = ""):
        self.token = token
        self.ssh_key_file = ssh_key_file
        self._session = requests.Session()

        # Gitee fronts api.gitee.com with a WAF that blocks bursts of concurrent
        # requests from the same IP as a security risk (403, even though the
        # token itself is fine). Serialize all Gitee REST calls with a minimum
        # gap between them so N parallel workers don't all hit the API in the
        # same instant -- clone/push over SSH is unaffected and stays parallel.
        self._lock = threading.Lock()
        self._min_interval = 0.5
        self._last_call = 0.0

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        with self._lock:
            wait = self._min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            try:
                return self._session.request(method, url, timeout=30, **kwargs)
            finally:
                self._last_call = time.monotonic()

    def list_repos(self, org: str) -> List[RepoRef]:
        repos: List[RepoRef] = []
        page = 1
        while True:
            resp = self._request(
                "GET",
                f"{API}/orgs/{org}/repos",
                params={"access_token": self.token, "per_page": 100, "page": page},
            )
            resp.raise_for_status()
            items = resp.json()
            if not items:
                break
            repos.extend(
                RepoRef(item["name"], item["default_branch"]) for item in items
            )
            page += 1
        return repos

    def default_branch(self, org: str, repo: str) -> Optional[str]:
        resp = self._request(
            "GET", f"{API}/repos/{org}/{repo}", params={"access_token": self.token}
        )
        if resp.status_code != 200:
            return None
        return resp.json().get("default_branch")

    def branch_sha(self, org: str, repo: str, branch: str) -> Optional[str]:
        resp = self._request(
            "GET",
            f"{API}/repos/{org}/{repo}/branches/{branch}",
            params={"access_token": self.token},
        )
        if resp.status_code != 200:
            return None
        return resp.json().get("commit", {}).get("sha")

    def _repo_exists(self, org: str, repo: str) -> bool:
        resp = self._request(
            "GET", f"{API}/repos/{org}/{repo}", params={"access_token": self.token}
        )
        if resp.status_code == 200:
            return True
        if resp.status_code == 404:
            return False
        # Anything else (rate limiting, transient 5xx, ...) is not a reliable
        # signal that the repo is missing -- surface it instead of silently
        # treating it as "doesn't exist", which would trigger a spurious
        # (and failing) create call.
        raise RuntimeError(
            f"unexpected status checking {org}/{repo} on Gitee: {resp.status_code} {resp.text}"
        )

    def _create_repo(self, org: str, repo: str) -> None:
        resp = self._request(
            "POST",
            f"{API}/orgs/{org}/repos",
            data={"name": repo, "access_token": self.token},
        )
        if resp.status_code == 201:
            # Gitee needs a moment before the new repo is ready to receive a push.
            time.sleep(2)
            return
        if resp.status_code == 422 and "已存在同地址仓库" in resp.text:
            raise GiteeRepoExistsError(f"{org}/{repo} already exists on Gitee")
        raise RuntimeError(
            f"failed to create {org}/{repo} on Gitee: {resp.status_code} {resp.text}"
        )

    def ensure_repo(self, org: str, repo: str) -> None:
        if _retry(self._repo_exists, org, repo):
            return
        logger.info(f"{repo}: doesn't exist on Gitee, creating")
        try:
            self._create_repo(org, repo)
        except GiteeRepoExistsError:
            logger.info(f"{repo}: already existed on Gitee (race), continuing")

    def clone_url(self, org: str, repo: str) -> str:
        return f"git@gitee.com:{org}/{repo}.git"

    def push_url(self, org: str, repo: str) -> str:
        return f"git@gitee.com:{org}/{repo}.git"

    def git_env(self) -> Dict[str, str]:
        return {
            "GIT_SSH_COMMAND": (
                f"ssh -i {self.ssh_key_file} -o StrictHostKeyChecking=no "
                "-o IdentitiesOnly=yes"
            )
        }
