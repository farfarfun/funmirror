"""GitCode REST API v5 platform."""

from typing import Dict, List, Optional

import requests
from farlog import get_logger

from funmirror.sync.platforms.base import Platform, RepoRef

logger = get_logger("funmirror")

API = "https://api.gitcode.com/api/v5"


class GitCodePlatform(Platform):
    name = "gitcode"

    def __init__(self, token: str = ""):
        self.token = token
        self._session = requests.Session()

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

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
                RepoRef(item["name"], item.get("default_branch") or "master")
                for item in items
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
        return resp.json().get("commit", {}).get("id")

    def ensure_repo(self, org: str, repo: str) -> None:
        resp = self._session.get(
            f"{API}/repos/{org}/{repo}", headers=self._headers(), timeout=30
        )
        if resp.status_code == 200:
            return
        if resp.status_code != 404:
            raise RuntimeError(
                f"unexpected status checking {org}/{repo} on GitCode: "
                f"{resp.status_code} {resp.text}"
            )
        logger.info(f"{repo}: doesn't exist on GitCode, creating")
        resp = self._session.post(
            f"{API}/orgs/{org}/repos",
            json={"name": repo},
            headers=self._headers(),
            timeout=30,
        )
        if resp.status_code in (200, 201):
            return
        text_lower = resp.text.lower()
        if resp.status_code in (400, 409, 422) and (
            "already exist" in text_lower or "已存在" in resp.text
        ):
            logger.info(f"{repo}: already existed on GitCode (race), continuing")
            return
        raise RuntimeError(
            f"failed to create {org}/{repo} on GitCode: {resp.status_code} {resp.text}"
        )

    def clone_url(self, org: str, repo: str) -> str:
        if self.token:
            return f"https://oauth2:{self.token}@gitcode.com/{org}/{repo}.git"
        return f"https://gitcode.com/{org}/{repo}.git"

    def push_url(self, org: str, repo: str) -> str:
        return self.clone_url(org, repo)
