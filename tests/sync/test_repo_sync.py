from unittest.mock import Mock, patch

from funmirror.sync.platforms.base import Platform, RepoRef
from funmirror.sync.repo_sync import SyncContext, SyncResult, detect_repo, sync_repo


def _ctx() -> SyncContext:
    return SyncContext(
        src=Mock(spec=Platform),
        dst=Mock(spec=Platform),
        workdir="/tmp/does-not-matter",
    )


def test_detect_full_sync_terminal_skip_when_shas_match():
    ctx = _ctx()
    ctx.src.branch_sha.return_value = "abc123"
    ctx.dst.branch_sha.return_value = "abc123"

    result = detect_repo(RepoRef("repo1", "main"), "src-org", "dst-org", ctx)

    assert result.outcome == "terminal"
    assert result.result.status == "skipped"
    assert result.result.src_sha == "abc123"
    assert result.result.dst_sha == "abc123"
    ctx.dst.ensure_repo.assert_not_called()


def test_detect_full_sync_needs_sync_when_shas_differ():
    ctx = _ctx()
    ctx.src.branch_sha.return_value = "abc123"
    ctx.dst.branch_sha.return_value = "xyz789"

    result = detect_repo(RepoRef("repo1", "main"), "src-org", "dst-org", ctx)

    assert result.outcome == "sync"
    assert result.src_sha == "abc123"


def test_detect_full_sync_ignores_state_file_for_the_decision():
    ctx = _ctx()
    ctx.src.branch_sha.return_value = "abc123"
    ctx.dst.branch_sha.return_value = "xyz789"

    result = detect_repo(
        RepoRef("repo1", "main"),
        "src-org",
        "dst-org",
        ctx,
        state_entry={"src_sha": "abc123", "dst_sha": "abc123"},
        incremental=False,
    )

    assert result.outcome == "sync"


def test_detect_incremental_skips_without_querying_dst_when_state_matches():
    ctx = _ctx()
    ctx.src.branch_sha.return_value = "abc123"

    result = detect_repo(
        RepoRef("repo1", "main"),
        "src-org",
        "dst-org",
        ctx,
        state_entry={"src_sha": "abc123", "dst_sha": "abc123"},
        incremental=True,
    )

    assert result.outcome == "terminal"
    assert result.result.status == "skipped"
    assert result.result.src_sha == "abc123"
    assert result.result.dst_sha == "abc123"
    ctx.dst.branch_sha.assert_not_called()
    ctx.dst.ensure_repo.assert_not_called()


def test_detect_incremental_goes_straight_to_sync_without_querying_dst_when_state_differs():
    ctx = _ctx()
    ctx.src.branch_sha.return_value = "abc123"

    result = detect_repo(
        RepoRef("repo1", "main"),
        "src-org",
        "dst-org",
        ctx,
        state_entry={"src_sha": "old-sha", "dst_sha": "old-sha"},
        incremental=True,
    )

    assert result.outcome == "sync"
    assert result.src_sha == "abc123"
    ctx.dst.branch_sha.assert_not_called()
    ctx.dst.ensure_repo.assert_not_called()


def test_detect_incremental_goes_straight_to_sync_without_state():
    ctx = _ctx()
    ctx.src.branch_sha.return_value = "abc123"

    result = detect_repo(
        RepoRef("repo1", "main"), "src-org", "dst-org", ctx, state_entry=None, incremental=True
    )

    assert result.outcome == "sync"
    ctx.dst.branch_sha.assert_not_called()


def test_detect_reports_failure_instead_of_raising():
    ctx = _ctx()
    ctx.src.branch_sha.side_effect = RuntimeError("boom")

    result = detect_repo(RepoRef("repo1", "main"), "src-org", "dst-org", ctx)

    assert result.outcome == "terminal"
    assert result.result.status == "failed"
    assert "boom" in result.result.detail


def test_sync_repo_ensures_dst_then_clones_and_pushes():
    ctx = _ctx()

    with patch(
        "funmirror.sync.repo_sync._clone_and_push",
        return_value=SyncResult("repo1", "mirrored"),
    ) as clone_and_push:
        result = sync_repo(RepoRef("repo1", "main"), "src-org", "dst-org", ctx, "abc123")

    ctx.dst.ensure_repo.assert_called_once_with("dst-org", "repo1")
    clone_and_push.assert_called_once()
    assert result.status == "mirrored"
    assert result.src_sha == "abc123"
    assert result.dst_sha == "abc123"  # mirrored -> dst now matches src


def test_sync_repo_does_not_set_dst_sha_when_not_mirrored():
    ctx = _ctx()

    with patch(
        "funmirror.sync.repo_sync._clone_and_push",
        return_value=SyncResult("repo1", "skipped", "empty repo"),
    ):
        result = sync_repo(RepoRef("repo1", "main"), "src-org", "dst-org", ctx, "abc123")

    assert result.src_sha == "abc123"
    assert result.dst_sha is None


def test_sync_repo_reports_failure_instead_of_raising():
    ctx = _ctx()
    ctx.dst.ensure_repo.side_effect = RuntimeError("boom")

    result = sync_repo(RepoRef("repo1", "main"), "src-org", "dst-org", ctx, "abc123")

    assert result.status == "failed"
    assert "boom" in result.detail
