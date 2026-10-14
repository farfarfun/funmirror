"""Gitee REST API platform."""

import os
import subprocess
import threading
import time
from typing import Dict, List, Optional, Tuple

import requests
from farlog import get_logger

from funmirror.sync.platforms.base import Platform, Release, ReleaseAsset, RepoRef

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
    writes_releases = True

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

        # Ref lookups go over the git transport instead (see branch_sha), which
        # is a different front door and not behind that WAF -- so they get to
        # run in parallel. Bounded all the same: 8 is what the sync phase
        # already pushes at, i.e. the one concurrency we have evidence Gitee
        # tolerates. Detect runs 32 workers by default and they would otherwise
        # all land at once.
        self._git_slots = threading.BoundedSemaphore(8)

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        # setdefault, not a positional timeout=30: asset uploads need minutes,
        # and passing their own timeout= must not collide with ours.
        kwargs.setdefault("timeout", 30)
        with self._lock:
            wait = self._min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            try:
                return self._session.request(method, url, **kwargs)
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
        """Head commit of org/repo's `branch`, read over the git transport.

        Deliberately not `GET /repos/{org}/{repo}/branches/{branch}`. A full
        sync asks for exactly one of these per repo, and every REST call is
        serialized by the throttle above: 139 repos measured at ~164 seconds,
        which was 95% of the entire run's wall clock and nearly all of it spent
        waiting out the minimum interval. `git ls-remote` answers the same
        question, isn't rate-limited the same way, and runs eight at a time.
        """
        with self._git_slots:
            proc = subprocess.run(
                [
                    "git",
                    # Nothing here may ever block on a human. An inherited
                    # credential helper will happily sit there forever being
                    # asked for a password nobody is going to type, and it
                    # holds one of the eight slots above the entire time --
                    # observed hanging a lookup for a full two minutes.
                    "-c",
                    "credential.helper=",
                    "ls-remote",
                    self.clone_url(org, repo),
                    f"refs/heads/{branch}",
                ],
                env=self._git_subprocess_env(),
                capture_output=True,
                text=True,
                # Backstop for a connection that dies without saying so. Well
                # clear of a slow cross-border lookup, well short of letting
                # one bad repo stall a slot for minutes.
                timeout=60,
            )
        if proc.returncode != 0:
            # Same verdict the REST version gave for any non-200, and for the
            # same reason: we don't know, so let the destination be treated as
            # stale and have phase 2 settle it with an authoritative
            # ensure_repo. Far and away the usual cause is a repo that simply
            # isn't on this side yet.
            #
            # Being this relaxed is only safe because the one failure that
            # would really hurt -- SSH to gitee.com down, turning all 139 repos
            # into needless clone+pushes -- can't reach here: the mirror-repo
            # action's ssh-keyscan preflight fails the run first.
            logger.debug(f"{repo}: ls-remote failed: {proc.stderr.strip()}")
            return None
        line = proc.stdout.strip()
        # Exit 0 with nothing on stdout means the repo is there, the branch isn't.
        return line.split()[0] if line else None

    def _git_subprocess_env(self) -> Dict[str, str]:
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        # GIT_TERMINAL_PROMPT only closes the terminal door. git still reaches
        # for an askpass helper when it has one, and an editor's helper
        # (VS Code exports GIT_ASKPASS unconditionally) will block forever
        # rather than return, which is how a single lookup sat for two minutes
        # holding a slot. CI runners don't set these; developer shells do, and
        # running funmirror by hand is the case this tool exists for.
        for var in ("GIT_ASKPASS", "SSH_ASKPASS"):
            env.pop(var, None)
        env.update(self.git_env())
        return env

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
        # No key configured: say nothing and let ssh use whatever the host
        # already has (agent, ~/.ssh/id_*). Interpolating an empty path here
        # would build `ssh -i  -o StrictHostKeyChecking=no ...`, where -i eats
        # the following -o and the option silently goes missing.
        if not self.ssh_key_file:
            return {}
        return {
            # BatchMode for the same reason the credential helper is disabled
            # in branch_sha: ssh must fail rather than stop and ask for a
            # passphrase. Nothing calling this has a terminal attached.
            "GIT_SSH_COMMAND": (
                f"ssh -i {self.ssh_key_file} -o StrictHostKeyChecking=no "
                "-o IdentitiesOnly=yes -o BatchMode=yes"
            )
        }

    # --- releases -----------------------------------------------------------

    def _release_by_tag(self, org: str, repo: str, tag: str) -> Optional[dict]:
        resp = self._request(
            "GET",
            f"{API}/repos/{org}/{repo}/releases/tags/{tag}",
            params={"access_token": self.token},
        )
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise RuntimeError(
                f"unexpected status reading release {tag} of {org}/{repo}: "
                f"{resp.status_code} {resp.text}"
            )
        return resp.json()

    def ensure_release(self, org: str, repo: str, release: Release) -> Tuple[str, bool]:
        existing = _retry(self._release_by_tag, org, repo, release.tag)
        if existing:
            return str(existing["id"]), False

        resp = self._request(
            "POST",
            f"{API}/repos/{org}/{repo}/releases",
            data={
                "access_token": self.token,
                "tag_name": release.tag,
                "name": release.name or release.tag,
                # Gitee rejects an empty body outright ("发行版的描述不能为空"),
                # and GitHub releases cut by a CI job very often have one.
                "body": release.body or release.name or release.tag,
                "prerelease": "true" if release.prerelease else "false",
                "target_commitish": release.target_commitish or "master",
            },
        )
        if resp.status_code in (200, 201):
            return str(resp.json()["id"]), True
        # Another worker (or a previous half-finished run) got there first.
        if resp.status_code in (400, 422):
            existing = self._release_by_tag(org, repo, release.tag)
            if existing:
                return str(existing["id"]), False
        raise RuntimeError(
            f"failed to create release {release.tag} on {org}/{repo}: "
            f"{resp.status_code} {resp.text}"
        )

    def release_assets(self, org: str, repo: str, release_id: str) -> List[ReleaseAsset]:
        resp = self._request(
            "GET",
            f"{API}/repos/{org}/{repo}/releases/{release_id}/attach_files",
            params={"access_token": self.token, "per_page": 100},
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        # Gitee's auto-generated source archives ({tag}.zip / {tag}.tar.gz) are
        # not attach_files, so they never show up here and never collide with
        # a real asset of the same name.
        return [
            ReleaseAsset(
                name=item["name"],
                size=item.get("size", -1),
                id=str(item["id"]),
            )
            for item in resp.json()
        ]

    def upload_asset(self, org: str, repo: str, release_id: str, path: str) -> None:
        with open(path, "rb") as fh:
            resp = self._request(
                "POST",
                f"{API}/repos/{org}/{repo}/releases/{release_id}/attach_files",
                data={"access_token": self.token},
                files={"file": (os.path.basename(path), fh)},
                # The throttling lock is held for the whole upload, so this is
                # also how long every other Gitee call can be stalled. Generous
                # anyway: a few hundred MB over a slow link from a CI runner.
                timeout=600,
            )
        if resp.status_code in (200, 201):
            return
        raise RuntimeError(
            f"failed to upload {os.path.basename(path)} to release "
            f"{release_id} of {org}/{repo}: {resp.status_code} {resp.text}"
        )

    def delete_asset(
        self, org: str, repo: str, release_id: str, asset: ReleaseAsset
    ) -> None:
        resp = self._request(
            "DELETE",
            f"{API}/repos/{org}/{repo}/releases/{release_id}/attach_files/{asset.id}",
            params={"access_token": self.token},
        )
        if resp.status_code in (200, 204, 404):
            return
        raise RuntimeError(
            f"failed to delete attachment {asset.name} from release "
            f"{release_id} of {org}/{repo}: {resp.status_code} {resp.text}"
        )
