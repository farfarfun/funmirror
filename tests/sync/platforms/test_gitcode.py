from unittest.mock import Mock, patch

from funmirror.sync.platforms.gitcode import GitCodePlatform


def _platform() -> GitCodePlatform:
    return GitCodePlatform(token="token")


def _resp(status_code: int, json_body=None, text: str = ""):
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.text = text
    resp.raise_for_status = Mock()
    return resp


def test_ensure_repo_noop_when_already_exists():
    platform = _platform()
    with patch.object(
        platform._session, "get", return_value=_resp(200)
    ) as get, patch.object(platform._session, "post") as post:
        platform.ensure_repo("org", "repo1")

    get.assert_called_once()
    post.assert_not_called()


def test_ensure_repo_creates_when_missing():
    platform = _platform()
    with patch.object(
        platform._session, "get", return_value=_resp(404)
    ), patch.object(
        platform._session, "post", return_value=_resp(201)
    ) as post:
        platform.ensure_repo("org", "repo1")

    _, kwargs = post.call_args
    assert kwargs["json"]["name"] == "repo1"


def test_ensure_repo_survives_create_race_when_repo_already_exists():
    platform = _platform()
    with patch.object(
        platform._session, "get", return_value=_resp(404)
    ), patch.object(
        platform._session,
        "post",
        return_value=_resp(422, text="repo already exists"),
    ):
        platform.ensure_repo("org", "repo1")  # must not raise


def test_clone_url_embeds_token():
    platform = _platform()
    assert platform.clone_url("org", "repo1") == (
        "https://oauth2:token@gitcode.com/org/repo1.git"
    )


def test_branch_sha_returns_none_on_missing_branch():
    platform = _platform()
    with patch.object(platform._session, "get", return_value=_resp(404)):
        assert platform.branch_sha("org", "repo1", "main") is None
