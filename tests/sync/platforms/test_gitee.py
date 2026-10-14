from unittest.mock import Mock, patch

from funmirror.sync.platforms.base import Release
from funmirror.sync.platforms.gitee import GiteePlatform


def _platform() -> GiteePlatform:
    return GiteePlatform(token="token", ssh_key_file="/tmp/does-not-matter")


def _resp(status_code: int, json_body=None, text: str = ""):
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.text = text
    return resp


def test_ensure_repo_creates_when_missing():
    platform = _platform()
    with patch.object(
        platform._session,
        "request",
        side_effect=[_resp(404), _resp(201)],
    ) as request:
        platform.ensure_repo("org", "repo1")

    assert request.call_count == 2


def test_ensure_repo_noop_when_already_exists():
    platform = _platform()
    with patch.object(platform._session, "request", return_value=_resp(200)) as request:
        platform.ensure_repo("org", "repo1")

    request.assert_called_once()


def test_ensure_repo_survives_create_race_when_repo_already_exists():
    """_repo_exists said False (e.g. a transient miss), but the create call
    then reports the repo already exists -- this must not be treated as a failure."""
    platform = _platform()
    with patch.object(
        platform._session,
        "request",
        side_effect=[
            _resp(404),
            _resp(422, text="已存在同地址仓库（忽略大小写）"),
        ],
    ):
        platform.ensure_repo("org", "repo1")  # must not raise


def test_request_throttles_consecutive_calls():
    platform = _platform()
    platform._min_interval = 0.05
    with patch.object(platform._session, "request", return_value=_resp(200)):
        with patch("funmirror.sync.platforms.gitee.time.sleep") as sleep:
            platform._request("GET", "https://gitee.com/api/v5/x")
            platform._request("GET", "https://gitee.com/api/v5/x")

    assert sleep.called


def test_ensure_release_reuses_an_existing_one_by_tag():
    platform = _platform()
    with patch.object(
        platform._session, "request", return_value=_resp(200, {"id": 9})
    ) as request:
        release_id, created = platform.ensure_release("org", "repo1", Release(tag="v1"))

    assert (release_id, created) == ("9", False)
    request.assert_called_once()


def test_ensure_release_creates_when_the_tag_has_none():
    platform = _platform()
    with patch.object(
        platform._session,
        "request",
        side_effect=[_resp(404), _resp(201, {"id": 11})],
    ):
        release_id, created = platform.ensure_release("org", "repo1", Release(tag="v1"))

    assert (release_id, created) == ("11", True)


def test_ensure_release_never_posts_an_empty_body():
    """Gitee rejects a release with no description outright, and GitHub
    releases cut by a CI job very often have one."""
    platform = _platform()
    with patch.object(
        platform._session,
        "request",
        side_effect=[_resp(404), _resp(201, {"id": 11})],
    ) as request:
        platform.ensure_release("org", "repo1", Release(tag="v1"))

    assert request.call_args.kwargs["data"]["body"] == "v1"


def test_ensure_release_survives_a_create_race():
    platform = _platform()
    with patch.object(
        platform._session,
        "request",
        side_effect=[
            _resp(404),
            _resp(400, text="发行版的标签已存在"),
            _resp(200, {"id": 13}),
        ],
    ):
        release_id, created = platform.ensure_release("org", "repo1", Release(tag="v1"))

    assert (release_id, created) == ("13", False)


def test_release_assets_carries_the_attachment_id_for_deletion():
    platform = _platform()
    body = [{"id": 7, "name": "a.tar.gz", "size": 10}]
    with patch.object(platform._session, "request", return_value=_resp(200, body)):
        assets = platform.release_assets("org", "repo1", "9")

    assert [(a.name, a.size, a.id) for a in assets] == [("a.tar.gz", 10, "7")]


def test_upload_asset_posts_multipart(tmp_path):
    platform = _platform()
    path = tmp_path / "a.tar.gz"
    path.write_bytes(b"payload")
    with patch.object(
        platform._session, "request", return_value=_resp(201)
    ) as request:
        platform.upload_asset("org", "repo1", "9", str(path))

    assert request.call_args.kwargs["files"]["file"][0] == "a.tar.gz"
    # Upload timeouts are minutes, not the 30s the read calls use.
    assert request.call_args.kwargs["timeout"] == 600


def test_request_timeout_can_be_overridden():
    platform = _platform()
    platform._min_interval = 0
    with patch.object(platform._session, "request", return_value=_resp(200)) as request:
        platform._request("GET", "https://gitee.com/api/v5/x")
        platform._request("POST", "https://gitee.com/api/v5/x", timeout=600)

    assert request.call_args_list[0].kwargs["timeout"] == 30
    assert request.call_args_list[1].kwargs["timeout"] == 600


def _proc(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return Mock(returncode=returncode, stdout=stdout, stderr=stderr)


def test_branch_sha_reads_the_ref_over_git_not_the_rest_api():
    platform = _platform()
    with patch(
        "funmirror.sync.platforms.gitee.subprocess.run",
        return_value=_proc(stdout="abc123\trefs/heads/main\n"),
    ) as run, patch.object(platform._session, "request") as request:
        assert platform.branch_sha("org", "repo1", "main") == "abc123"

    assert run.call_args[0][0] == [
        "git",
        "-c",
        "credential.helper=",
        "ls-remote",
        "git@gitee.com:org/repo1.git",
        "refs/heads/main",
    ]
    # The whole point: this call must not go near the throttled REST session.
    request.assert_not_called()


def test_branch_sha_is_none_when_the_branch_is_absent():
    """ls-remote exits 0 with no output when the repo is there and the ref isn't."""
    platform = _platform()
    with patch(
        "funmirror.sync.platforms.gitee.subprocess.run", return_value=_proc(stdout="")
    ):
        assert platform.branch_sha("org", "repo1", "main") is None


def test_branch_sha_is_none_when_ls_remote_fails():
    platform = _platform()
    with patch(
        "funmirror.sync.platforms.gitee.subprocess.run",
        return_value=_proc(returncode=128, stderr="Repository not found"),
    ):
        assert platform.branch_sha("org", "repo1", "main") is None


def test_branch_sha_passes_the_ssh_key_through_to_git():
    platform = _platform()
    with patch(
        "funmirror.sync.platforms.gitee.subprocess.run",
        return_value=_proc(stdout="abc123\trefs/heads/main\n"),
    ) as run:
        platform.branch_sha("org", "repo1", "main")

    env = run.call_args.kwargs["env"]
    assert "/tmp/does-not-matter" in env["GIT_SSH_COMMAND"]
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_git_env_is_empty_without_a_key_file():
    """`ssh -i '' -o ...` would have -i swallow the -o that follows it."""
    assert GiteePlatform(token="token").git_env() == {}


def test_branch_sha_strips_inherited_askpass_helpers():
    """An editor's askpass helper blocks forever instead of failing."""
    platform = _platform()
    with patch.dict(
        "os.environ", {"GIT_ASKPASS": "/vscode/askpass.sh", "SSH_ASKPASS": "/x"}
    ), patch(
        "funmirror.sync.platforms.gitee.subprocess.run",
        return_value=_proc(stdout="abc123\trefs/heads/main\n"),
    ) as run:
        platform.branch_sha("org", "repo1", "main")

    env = run.call_args.kwargs["env"]
    assert "GIT_ASKPASS" not in env
    assert "SSH_ASKPASS" not in env


def test_git_env_runs_ssh_in_batch_mode():
    assert "BatchMode=yes" in _platform().git_env()["GIT_SSH_COMMAND"]
