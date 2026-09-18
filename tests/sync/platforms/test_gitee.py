from unittest.mock import Mock, patch

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
