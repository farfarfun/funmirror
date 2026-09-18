"""GitHub / Gitee REST API helpers used by funmirror."""

import time
from typing import Dict, List, Optional

import requests

from farlog import get_logger

logger = get_logger("funmirror")

GITHUB_API = "https://api.github.com"
GITEE_API = "https://gitee.com/api/v5"

_session = requests.Session()


def _github_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"token {token}"} if token else {}


def list_github_repos(org: str, token: str = "", per_page: int = 100) -> List[Dict]:
    """List all repos in a GitHub org, with their default branch."""
    repos: List[Dict] = []
    page = 1
    while True:
        resp = _session.get(
            f"{GITHUB_API}/orgs/{org}/repos",
            params={"type": "all", "per_page": per_page, "page": page},
            headers=_github_headers(token),
            timeout=30,
        )
        resp.raise_for_status()
        items = resp.json()
        if not items:
            break
        repos.extend(
            {"name": item["name"], "default_branch": item["default_branch"]}
            for item in items
        )
        page += 1
    return repos


def github_default_branch(org: str, repo: str, token: str = "") -> Optional[str]:
    resp = _session.get(
        f"{GITHUB_API}/repos/{org}/{repo}", headers=_github_headers(token), timeout=30
    )
    if resp.status_code != 200:
        return None
    return resp.json().get("default_branch")


def github_branch_sha(org: str, repo: str, branch: str, token: str = "") -> Optional[str]:
    resp = _session.get(
        f"{GITHUB_API}/repos/{org}/{repo}/branches/{branch}",
        headers=_github_headers(token),
        timeout=30,
    )
    if resp.status_code != 200:
        return None
    return resp.json().get("commit", {}).get("sha")


def gitee_repo_exists(org: str, repo: str, token: str) -> bool:
    resp = _session.get(
        f"{GITEE_API}/repos/{org}/{repo}", params={"access_token": token}, timeout=30
    )
    return resp.status_code == 200


def gitee_branch_sha(org: str, repo: str, branch: str, token: str) -> Optional[str]:
    resp = _session.get(
        f"{GITEE_API}/repos/{org}/{repo}/branches/{branch}",
        params={"access_token": token},
        timeout=30,
    )
    if resp.status_code != 200:
        return None
    return resp.json().get("commit", {}).get("sha")


def gitee_create_repo(org: str, repo: str, token: str) -> None:
    resp = _session.post(
        f"{GITEE_API}/orgs/{org}/repos",
        data={"name": repo, "access_token": token},
        timeout=30,
    )
    if resp.status_code != 201:
        raise RuntimeError(
            f"failed to create {org}/{repo} on Gitee: {resp.status_code} {resp.text}"
        )
    # Gitee needs a moment before the new repo is ready to receive a push.
    time.sleep(2)
