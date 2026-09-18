from unittest.mock import patch

from funmirror.sync.mirror import MirrorContext, MirrorResult, mirror_one
from funmirror.sync.platforms import GiteeRepoExistsError


def _ctx() -> MirrorContext:
    return MirrorContext(
        github_org="org",
        gitee_org="org",
        gitee_token="token",
        gitee_key_file="/tmp/does-not-matter",
    )


def test_mirror_one_skips_when_sha_matches():
    ctx = _ctx()
    with (
        patch("funmirror.sync.mirror.platforms.github_branch_sha", return_value="abc123"),
        patch("funmirror.sync.mirror.platforms.gitee_repo_exists", return_value=True),
        patch("funmirror.sync.mirror.platforms.gitee_branch_sha", return_value="abc123"),
        patch("funmirror.sync.mirror._clone_and_push") as clone_and_push,
    ):
        result = mirror_one({"name": "repo1", "default_branch": "main"}, ctx)

    assert result.status == "skipped"
    clone_and_push.assert_not_called()


def test_mirror_one_mirrors_when_sha_differs():
    ctx = _ctx()
    with (
        patch("funmirror.sync.mirror.platforms.github_branch_sha", return_value="abc123"),
        patch("funmirror.sync.mirror.platforms.gitee_repo_exists", return_value=True),
        patch("funmirror.sync.mirror.platforms.gitee_branch_sha", return_value="xyz789"),
        patch(
            "funmirror.sync.mirror._clone_and_push",
            return_value=MirrorResult("repo1", "mirrored"),
        ) as clone_and_push,
    ):
        result = mirror_one({"name": "repo1", "default_branch": "main"}, ctx)

    assert result.status == "mirrored"
    clone_and_push.assert_called_once()


def test_mirror_one_creates_repo_when_missing_on_gitee():
    ctx = _ctx()
    with (
        patch("funmirror.sync.mirror.platforms.github_branch_sha", return_value="abc123"),
        patch("funmirror.sync.mirror.platforms.gitee_repo_exists", return_value=False),
        patch("funmirror.sync.mirror.platforms.gitee_create_repo") as create_repo,
        patch(
            "funmirror.sync.mirror._clone_and_push",
            return_value=MirrorResult("repo1", "mirrored"),
        ),
    ):
        result = mirror_one({"name": "repo1", "default_branch": "main"}, ctx)

    create_repo.assert_called_once_with("org", "repo1", "token")
    assert result.status == "mirrored"


def test_mirror_one_survives_create_race_when_repo_already_exists():
    """gitee_repo_exists said False (e.g. a transient miss), but the create call
    then reports the repo already exists -- this must not be treated as a failure."""
    ctx = _ctx()
    with (
        patch("funmirror.sync.mirror.platforms.github_branch_sha", return_value="abc123"),
        patch("funmirror.sync.mirror.platforms.gitee_repo_exists", return_value=False),
        patch(
            "funmirror.sync.mirror.platforms.gitee_create_repo",
            side_effect=GiteeRepoExistsError("org/repo1 already exists on Gitee"),
        ),
        patch("funmirror.sync.mirror.platforms.gitee_branch_sha", return_value="xyz789"),
        patch(
            "funmirror.sync.mirror._clone_and_push",
            return_value=MirrorResult("repo1", "mirrored"),
        ) as clone_and_push,
    ):
        result = mirror_one({"name": "repo1", "default_branch": "main"}, ctx)

    assert result.status == "mirrored"
    clone_and_push.assert_called_once()


def test_mirror_one_reports_failure_instead_of_raising():
    ctx = _ctx()
    with patch(
        "funmirror.sync.mirror.platforms.github_branch_sha", side_effect=RuntimeError("boom")
    ):
        result = mirror_one({"name": "repo1", "default_branch": "main"}, ctx)

    assert result.status == "failed"
    assert "boom" in result.detail
