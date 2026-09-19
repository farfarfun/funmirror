from unittest.mock import Mock, patch

from funmirror.sync.platforms.base import Platform, RepoRef
from funmirror.sync.repo_sync import SyncContext, SyncResult, sync_repo


def _ctx() -> SyncContext:
    return SyncContext(
        src=Mock(spec=Platform),
        dst=Mock(spec=Platform),
        workdir="/tmp/does-not-matter",
    )


def test_sync_repo_skips_when_sha_matches():
    ctx = _ctx()
    ctx.src.branch_sha.return_value = "abc123"
    ctx.dst.branch_sha.return_value = "abc123"

    with patch("funmirror.sync.repo_sync._clone_and_push") as clone_and_push:
        result = sync_repo(RepoRef("repo1", "main"), "src-org", "dst-org", ctx)

    assert result.status == "skipped"
    ctx.dst.ensure_repo.assert_called_once_with("dst-org", "repo1")
    clone_and_push.assert_not_called()


def test_sync_repo_syncs_when_sha_differs():
    ctx = _ctx()
    ctx.src.branch_sha.return_value = "abc123"
    ctx.dst.branch_sha.return_value = "xyz789"

    with patch(
        "funmirror.sync.repo_sync._clone_and_push",
        return_value=SyncResult("repo1", "mirrored"),
    ) as clone_and_push:
        result = sync_repo(RepoRef("repo1", "main"), "src-org", "dst-org", ctx)

    assert result.status == "mirrored"
    clone_and_push.assert_called_once()


def test_sync_repo_ensures_dst_repo_before_comparing_shas():
    ctx = _ctx()
    ctx.src.branch_sha.return_value = "abc123"
    ctx.dst.branch_sha.return_value = "abc123"

    with patch("funmirror.sync.repo_sync._clone_and_push"):
        sync_repo(RepoRef("repo1", "main"), "src-org", "dst-org", ctx)

    ctx.dst.ensure_repo.assert_called_once_with("dst-org", "repo1")


def test_sync_repo_reports_failure_instead_of_raising():
    ctx = _ctx()
    ctx.src.branch_sha.side_effect = RuntimeError("boom")

    result = sync_repo(RepoRef("repo1", "main"), "src-org", "dst-org", ctx)

    assert result.status == "failed"
    assert "boom" in result.detail


def test_sync_repo_incremental_skips_without_querying_dst_when_sha_matches_state():
    ctx = _ctx()
    ctx.src.branch_sha.return_value = "abc123"

    result = sync_repo(
        RepoRef("repo1", "main"),
        "src-org",
        "dst-org",
        ctx,
        state_sha="abc123",
        incremental=True,
    )

    assert result.status == "skipped"
    assert result.src_sha == "abc123"
    ctx.dst.ensure_repo.assert_not_called()
    ctx.dst.branch_sha.assert_not_called()


def test_sync_repo_incremental_falls_through_to_dst_check_when_sha_differs():
    ctx = _ctx()
    ctx.src.branch_sha.return_value = "abc123"
    ctx.dst.branch_sha.return_value = "abc123"

    result = sync_repo(
        RepoRef("repo1", "main"),
        "src-org",
        "dst-org",
        ctx,
        state_sha="old-sha",
        incremental=True,
    )

    assert result.status == "skipped"
    ctx.dst.ensure_repo.assert_called_once_with("dst-org", "repo1")


def test_sync_repo_records_src_sha_on_mirrored_result():
    ctx = _ctx()
    ctx.src.branch_sha.return_value = "abc123"
    ctx.dst.branch_sha.return_value = "xyz789"

    with patch(
        "funmirror.sync.repo_sync._clone_and_push",
        return_value=SyncResult("repo1", "mirrored"),
    ):
        result = sync_repo(RepoRef("repo1", "main"), "src-org", "dst-org", ctx)

    assert result.src_sha == "abc123"
