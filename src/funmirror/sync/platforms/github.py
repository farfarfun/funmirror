"""GitHub REST API platform."""

from typing import Dict, List, Optional

import requests
from farlog import get_logger

from funmirror.sync.platforms.base import Platform, Release, ReleaseAsset, RepoRef

logger = get_logger("funmirror")

API = "https://api.github.com"


class GitHubPlatform(Platform):
    name = "github"
    reads_releases = True

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

    def list_releases(self, org: str, repo: str) -> List[Release]:
        releases: List[Release] = []
        page = 1
        while True:
            resp = self._session.get(
                f"{API}/repos/{org}/{repo}/releases",
                params={"per_page": 100, "page": page},
                headers=self._headers(),
                timeout=30,
            )
            # A repo with releases disabled 404s here; that's "no releases",
            # not a failure worth taking the whole repo's sync down.
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            items = resp.json()
            if not items:
                break
            for item in items:
                if item.get("draft"):
                    continue
                releases.append(
                    Release(
                        tag=item["tag_name"],
                        name=item.get("name") or "",
                        body=item.get("body") or "",
                        prerelease=bool(item.get("prerelease")),
                        target_commitish=item.get("target_commitish") or "",
                        assets=[
                            ReleaseAsset(
                                name=a["name"],
                                size=a.get("size", -1),
                                # The API url (not browser_download_url) so
                                # private repos work too. requests drops the
                                # Authorization header on the cross-host
                                # redirect to object storage, which is exactly
                                # what S3 wants -- passing both auth
                                # mechanisms is an error there.
                                download_url=a["url"],
                            )
                            for a in item.get("assets", [])
                        ],
                    )
                )
            page += 1
        return releases

    def download_asset(self, asset: ReleaseAsset, dest_path: str) -> None:
        headers = dict(self._headers())
        headers["Accept"] = "application/octet-stream"
        with self._session.get(
            asset.download_url, headers=headers, stream=True, timeout=300
        ) as resp:
            resp.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
