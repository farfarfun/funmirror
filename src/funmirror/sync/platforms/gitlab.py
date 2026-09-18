"""GitLab REST API v4 platform."""

from typing import Dict, List, Optional
from urllib.parse import quote

import requests
from farlog import get_logger

from funmirror.sync.platforms.base import Platform, RepoRef

logger = get_logger("funmirror")


class GitLabPlatform(Platform):
    name = "gitlab"

    def __init__(self, token: str = "", endpoint: str = "gitlab.com"):
        self.token = token
        self.endpoint = endpoint
        self.api = f"https://{endpoint}/api/v4"
        self._session = requests.Session()

    def _headers(self) -> Dict[str, str]:
        return {"PRIVATE-TOKEN": self.token} if self.token else {}

    def _project_path(self, org: str, repo: str) -> str:
        return quote(f"{org}/{repo}", safe="")

    def list_repos(self, org: str) -> List[RepoRef]:
        repos: List[RepoRef] = []
        page = 1
        while True:
            resp = self._session.get(
                f"{self.api}/groups/{quote(org, safe='')}/projects",
                params={"include_subgroups": "false", "per_page": 100, "page": page},
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            items = resp.json()
            if not items:
                break
            repos.extend(
                RepoRef(item["path"], item.get("default_branch") or "master")
                for item in items
            )
            page += 1
        return repos

    def default_branch(self, org: str, repo: str) -> Optional[str]:
        resp = self._session.get(
            f"{self.api}/projects/{self._project_path(org, repo)}",
            headers=self._headers(),
            timeout=30,
        )
        if resp.status_code != 200:
            return None
        return resp.json().get("default_branch")

    def branch_sha(self, org: str, repo: str, branch: str) -> Optional[str]:
        resp = self._session.get(
            f"{self.api}/projects/{self._project_path(org, repo)}"
            f"/repository/branches/{quote(branch, safe='')}",
            headers=self._headers(),
            timeout=30,
        )
        if resp.status_code != 200:
            return None
        return resp.json().get("commit", {}).get("id")

    def _group_id(self, org: str) -> int:
        resp = self._session.get(
            f"{self.api}/groups/{quote(org, safe='')}",
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["id"]

    def ensure_repo(self, org: str, repo: str) -> None:
        resp = self._session.get(
            f"{self.api}/projects/{self._project_path(org, repo)}",
            headers=self._headers(),
            timeout=30,
        )
        if resp.status_code == 200:
            return
        if resp.status_code != 404:
            raise RuntimeError(
                f"unexpected status checking {org}/{repo} on GitLab: "
                f"{resp.status_code} {resp.text}"
            )
        logger.info(f"{repo}: doesn't exist on GitLab, creating")
        namespace_id = self._group_id(org)
        resp = self._session.post(
            f"{self.api}/projects",
            json={"name": repo, "path": repo, "namespace_id": namespace_id},
            headers=self._headers(),
            timeout=30,
        )
        if resp.status_code == 201:
            return
        if resp.status_code == 400 and "has already been taken" in resp.text:
            logger.info(f"{repo}: already existed on GitLab (race), continuing")
            return
        raise RuntimeError(
            f"failed to create {org}/{repo} on GitLab: {resp.status_code} {resp.text}"
        )

    def clone_url(self, org: str, repo: str) -> str:
        if self.token:
            return f"https://oauth2:{self.token}@{self.endpoint}/{org}/{repo}.git"
        return f"https://{self.endpoint}/{org}/{repo}.git"

    def push_url(self, org: str, repo: str) -> str:
        return self.clone_url(org, repo)
