from unittest.mock import Mock, patch

from funmirror.sync.platforms.base import Platform, RepoRef
from funmirror.sync.release_sync import ReleaseSyncSummary
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


def _release_ctx() -> SyncContext:
    ctx = _ctx()
    ctx.sync_releases = True
    return ctx


def test_detect_hands_an_up_to_date_repo_over_when_releases_are_on():
    """Publishing a release moves a tag, not the default branch. Skipping on
    the branch sha alone would make release mirroring miss exactly the case
    it exists for."""
    ctx = _release_ctx()
    ctx.src.branch_sha.return_value = "abc123"
    ctx.dst.branch_sha.return_value = "abc123"

    result = detect_repo(RepoRef("repo1", "main"), "src-org", "dst-org", ctx)

    assert result.outcome == "sync"
    assert result.git_up_to_date is True
    assert result.src_sha == "abc123"


def test_detect_incremental_still_hands_over_for_releases():
    ctx = _release_ctx()
    ctx.src.branch_sha.return_value = "abc123"

    result = detect_repo(
        RepoRef("repo1", "main"),
        "src-org",
        "dst-org",
        ctx,
        state_entry={"src_sha": "abc123", "dst_sha": "abc123"},
        incremental=True,
    )

    assert result.outcome == "sync"
    assert result.git_up_to_date is True


def test_sync_repo_skips_the_push_when_git_is_already_up_to_date():
    ctx = _release_ctx()

    with patch("funmirror.sync.repo_sync._clone_and_push") as clone_and_push:
        with patch(
            "funmirror.sync.repo_sync.sync_releases",
            return_value=ReleaseSyncSummary(),
        ):
            result = sync_repo(
                RepoRef("repo1", "main"), "src-org", "dst-org", ctx, "abc123", True
            )

    clone_and_push.assert_not_called()
    ctx.dst.ensure_repo.assert_not_called()
    assert result.status == "skipped"
    # A repo with no releases at all has nothing to add to the git verdict.
    assert result.detail == "up to date"


def test_sync_repo_says_so_when_the_release_pass_ran_and_found_nothing():
    """Otherwise a clean release pass logs identically to never having run
    one, which is exactly the thing this switch exists to make visible."""
    ctx = _release_ctx()

    with patch(
        "funmirror.sync.repo_sync.sync_releases",
        return_value=ReleaseSyncSummary(releases_checked=8),
    ):
        result = sync_repo(
            RepoRef("repo1", "main"), "src-org", "dst-org", ctx, "abc123", True
        )

    assert result.status == "skipped"
    assert result.detail == "up to date, 8 release(s) already there"


def test_sync_repo_reports_mirrored_when_only_releases_changed():
    ctx = _release_ctx()

    with patch(
        "funmirror.sync.repo_sync.sync_releases",
        return_value=ReleaseSyncSummary(releases_created=1, assets_uploaded=3),
    ):
        result = sync_repo(
            RepoRef("repo1", "main"), "src-org", "dst-org", ctx, "abc123", True
        )

    assert result.status == "mirrored"
    assert "1 release(s)" in result.detail and "3 asset(s)" in result.detail


def test_sync_repo_runs_releases_only_after_a_successful_push():
    """A Gitee release needs its tag to already be there; creating one first
    either fails or invents a tag off the wrong commit."""
    ctx = _release_ctx()
    calls = []

    with patch(
        "funmirror.sync.repo_sync._clone_and_push",
        side_effect=lambda *a: (calls.append("push"), SyncResult("repo1", "mirrored"))[1],
    ):
        with patch(
            "funmirror.sync.repo_sync.sync_releases",
            side_effect=lambda *a, **k: (calls.append("releases"), ReleaseSyncSummary())[1],
        ):
            sync_repo(RepoRef("repo1", "main"), "src-org", "dst-org", ctx, "abc123")

    assert calls == ["push", "releases"]


def test_sync_repo_fails_the_repo_when_release_sync_fails():
    ctx = _release_ctx()

    with patch(
        "funmirror.sync.repo_sync._clone_and_push",
        return_value=SyncResult("repo1", "mirrored"),
    ):
        with patch(
            "funmirror.sync.repo_sync.sync_releases", side_effect=RuntimeError("boom")
        ):
            result = sync_repo(
                RepoRef("repo1", "main"), "src-org", "dst-org", ctx, "abc123"
            )

    assert result.status == "failed"
    assert "boom" in result.detail
    # No state recorded, so the next run retries instead of trusting a
    # half-finished mirror.
    assert result.src_sha is None


def test_sync_repo_leaves_releases_alone_when_the_switch_is_off():
    ctx = _ctx()

    with patch(
        "funmirror.sync.repo_sync._clone_and_push",
        return_value=SyncResult("repo1", "mirrored"),
    ):
        with patch("funmirror.sync.repo_sync.sync_releases") as releases:
            sync_repo(RepoRef("repo1", "main"), "src-org", "dst-org", ctx, "abc123")

    releases.assert_not_called()
