from unittest.mock import Mock, patch

from funmirror.sync.platforms.gitlab import GitLabPlatform


def _platform() -> GitLabPlatform:
    return GitLabPlatform(token="token")


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
        platform.ensure_repo("group", "repo1")

    get.assert_called_once()
    post.assert_not_called()


def test_ensure_repo_creates_when_missing():
    platform = _platform()
    with patch.object(
        platform._session,
        "get",
        side_effect=[_resp(404), _resp(200, json_body={"id": 42})],
    ), patch.object(
        platform._session, "post", return_value=_resp(201)
    ) as post:
        platform.ensure_repo("group", "repo1")

    _, kwargs = post.call_args
    assert kwargs["json"]["namespace_id"] == 42
    assert kwargs["json"]["name"] == "repo1"


def test_ensure_repo_survives_create_race_when_repo_already_exists():
    """The existence check said 404, but the create call then reports the
    path has already been taken -- this must not be treated as a failure."""
    platform = _platform()
    with patch.object(
        platform._session,
        "get",
        side_effect=[_resp(404), _resp(200, json_body={"id": 42})],
    ), patch.object(
        platform._session,
        "post",
        return_value=_resp(
            400, text='{"message":{"path":["has already been taken"]}}'
        ),
    ):
        platform.ensure_repo("group", "repo1")  # must not raise


def test_clone_url_embeds_token():
    platform = _platform()
    assert platform.clone_url("group", "repo1") == (
        "https://oauth2:token@gitlab.com/group/repo1.git"
    )


def test_self_hosted_endpoint_used_in_api_and_urls():
    platform = GitLabPlatform(token="token", endpoint="gitlab.example.com")
    assert platform.api == "https://gitlab.example.com/api/v4"
    assert platform.clone_url("group", "repo1") == (
        "https://oauth2:token@gitlab.example.com/group/repo1.git"
    )
