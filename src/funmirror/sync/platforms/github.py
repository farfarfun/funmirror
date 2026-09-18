"""GitHub REST API platform."""

from typing import Dict, List, Optional

import requests
from farlog import get_logger

from funmirror.sync.platforms.base import Platform, RepoRef

logger = get_logger("funmirror")

API = "https://api.github.com"


class GitHubPlatform(Platform):
    name = "github"

    def __init__(self, token: str = ""):
        self.token = token
        self._session = requests.Session()

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"token {self.token}"} if self.token else {}

    def list_repos(self, org: str) -> List[RepoRef]:
        repos: List[RepoRef] = []
        page = 1
        while True:
            resp = self._session.get(
                f"{API}/orgs/{org}/repos",
                params={"type": "all", "per_page": 100, "page": page},
                headers=self._headers(),
                timeout=30,
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
        resp = self._session.get(
            f"{API}/repos/{org}/{repo}", headers=self._headers(), timeout=30
        )
        if resp.status_code != 200:
            return None
        return resp.json().get("default_branch")

    def branch_sha(self, org: str, repo: str, branch: str) -> Optional[str]:
        resp = self._session.get(
            f"{API}/repos/{org}/{repo}/branches/{branch}",
            headers=self._headers(),
            timeout=30,
        )
        if resp.status_code != 200:
            return None
        return resp.json().get("commit", {}).get("sha")

    def ensure_repo(self, org: str, repo: str) -> None:
        resp = self._session.get(
            f"{API}/repos/{org}/{repo}", headers=self._headers(), timeout=30
        )
        if resp.status_code == 200:
            return
        if resp.status_code != 404:
            raise RuntimeError(
                f"unexpected status checking {org}/{repo} on GitHub: "
                f"{resp.status_code} {resp.text}"
            )
        logger.info(f"{repo}: doesn't exist on GitHub, creating")
        resp = self._session.post(
            f"{API}/orgs/{org}/repos",
            json={"name": repo},
            headers=self._headers(),
            timeout=30,
        )
        if resp.status_code == 201:
            return
        if resp.status_code == 422 and "already exists" in resp.text:
            return
        raise RuntimeError(
            f"failed to create {org}/{repo} on GitHub: {resp.status_code} {resp.text}"
        )

    def clone_url(self, org: str, repo: str) -> str:
        if self.token:
            return f"https://x-access-token:{self.token}@github.com/{org}/{repo}.git"
        return f"https://github.com/{org}/{repo}.git"

    def push_url(self, org: str, repo: str) -> str:
        return self.clone_url(org, repo)
