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
