from unittest.mock import Mock, patch

import pytest

from funmirror.sync.org_sync import sync_org
from funmirror.sync.platforms.base import Platform, RepoRef
from funmirror.sync.repo_sync import SyncContext, SyncResult


def _ctx() -> SyncContext:
    return SyncContext(src=Mock(spec=Platform), dst=Mock(spec=Platform))


def test_sync_org_incremental_skips_unchanged_repo_without_touching_dst():
    ctx = _ctx()
    ctx.src.default_branch.return_value = "main"
    ctx.src.branch_sha.return_value = "abc123"

    consumer = sync_org(
        ctx,
        "src-org",
        "dst-org",
        repo_names=["repo1"],
        state={"repo1": {"src_sha": "abc123", "dst_sha": "abc123"}},
        incremental=True,
    )

    assert consumer.skipped == ["repo1"]
    ctx.dst.branch_sha.assert_not_called()
    ctx.dst.ensure_repo.assert_not_called()
    assert consumer.state_updates == {"repo1": {"src_sha": "abc123", "dst_sha": "abc123"}}


def test_sync_org_incremental_syncs_changed_repo_without_a_dst_read_first():
    ctx = _ctx()
    ctx.src.default_branch.return_value = "main"
    ctx.src.branch_sha.return_value = "new-sha"
    ctx.dst.ensure_repo.return_value = None

    from unittest.mock import patch
    from funmirror.sync.repo_sync import SyncResult

    with patch(
        "funmirror.sync.org_sync.sync_repo",
        return_value=SyncResult("repo1", "mirrored", src_sha="new-sha", dst_sha="new-sha"),
    ):
        consumer = sync_org(
            ctx,
            "src-org",
            "dst-org",
            repo_names=["repo1"],
            state={"repo1": {"src_sha": "old-sha", "dst_sha": "old-sha"}},
            incremental=True,
        )

    ctx.dst.branch_sha.assert_not_called()
    assert consumer.mirrored == ["repo1"]
    assert consumer.state_updates == {"repo1": {"src_sha": "new-sha", "dst_sha": "new-sha"}}


def test_sync_org_full_sync_collects_state_updates_for_mirrored_and_skipped_not_failed():
    ctx = _ctx()
    ctx.src.default_branch.return_value = "main"
    ctx.src.list_repos.return_value = [
        RepoRef("ok", "main"),
        RepoRef("boom", "main"),
    ]
    ctx.src.branch_sha.side_effect = lambda org, name, branch: (
        "sha-ok" if name == "ok" else "sha-boom"
    )
    ctx.dst.branch_sha.return_value = "sha-ok"  # matches "ok", not "boom"
    ctx.dst.ensure_repo.side_effect = lambda org, name: (
        (_ for _ in ()).throw(RuntimeError("dst down")) if name == "boom" else None
    )

    consumer = sync_org(ctx, "src-org", "dst-org", num_workers=1)

    assert consumer.skipped == ["ok"]
    assert consumer.failed == ["boom"]
    assert consumer.state_updates == {"ok": {"src_sha": "sha-ok", "dst_sha": "sha-ok"}}


def _release_ctx() -> SyncContext:
    """Mock(spec=Platform) picks up the class attribute defaults (both False),
    so a release-capable pair has to say so explicitly."""
    ctx = SyncContext(src=Mock(spec=Platform), dst=Mock(spec=Platform))
    ctx.sync_releases = True
    ctx.src.reads_releases = True
    ctx.dst.writes_releases = True
    return ctx


def test_sync_org_rejects_a_platform_pair_that_cannot_do_releases():
    """One line up front beats the same failure repeated once per repo."""
    ctx = _release_ctx()
    ctx.dst.writes_releases = False
    ctx.dst.name = "gitlab"

    with pytest.raises(ValueError, match="gitlab cannot be a release destination"):
        sync_org(ctx, "src-org", "dst-org", repo_names=["repo1"])


def test_sync_org_rejects_a_source_that_cannot_read_releases():
    ctx = _release_ctx()
    ctx.src.reads_releases = False
    ctx.src.name = "gitcode"

    with pytest.raises(ValueError, match="gitcode cannot be a release source"):
        sync_org(ctx, "src-org", "dst-org", repo_names=["repo1"])


def test_sync_org_still_runs_phase_two_for_an_up_to_date_repo_when_releases_are_on():
    ctx = _release_ctx()
    ctx.src.default_branch.return_value = "main"
    ctx.src.branch_sha.return_value = "abc123"
    ctx.dst.branch_sha.return_value = "abc123"

    with patch(
        "funmirror.sync.org_sync.sync_repo",
        return_value=SyncResult("repo1", "mirrored", "1 asset(s)", "abc123", "abc123"),
    ) as sync:
        consumer = sync_org(ctx, "src-org", "dst-org", repo_names=["repo1"])

    assert consumer.mirrored == ["repo1"]
    # The git_up_to_date flag has to reach phase 2, or it re-clones a repo it
    # just proved was identical.
    assert sync.call_args[0][5] is True


def test_named_repos_are_resolved_with_one_listing_not_one_call_each():
    ctx = _ctx()
    names = ["repo1", "repo2", "repo3", "repo4"]
    ctx.src.list_repos.return_value = [RepoRef(n, "main") for n in names]
    ctx.src.branch_sha.return_value = "abc123"
    ctx.dst.branch_sha.return_value = "abc123"

    consumer = sync_org(ctx, "src-org", "dst-org", repo_names=names)

    assert sorted(consumer.skipped) == names
    ctx.src.list_repos.assert_called_once_with("src-org")
    # One serialized round trip per repo is what this replaced.
    ctx.src.default_branch.assert_not_called()


def test_a_named_repo_outside_the_listing_still_gets_asked_about():
    ctx = _ctx()
    ctx.src.list_repos.return_value = [RepoRef("repo1", "main")]
    ctx.src.default_branch.return_value = "trunk"
    ctx.src.branch_sha.return_value = "abc123"
    ctx.dst.branch_sha.return_value = "abc123"

    sync_org(
        ctx, "src-org", "dst-org", repo_names=["repo1", "elsewhere", "x", "y"]
    )

    assert ctx.src.default_branch.call_args_list == [
        (("src-org", "elsewhere"),),
        (("src-org", "x"),),
        (("src-org", "y"),),
    ]
    assert ("src-org", "elsewhere", "trunk") in {
        tuple(c[0]) for c in ctx.src.branch_sha.call_args_list
    }


def test_a_handful_of_names_is_not_worth_paging_the_whole_org():
    ctx = _ctx()
    ctx.src.default_branch.return_value = "main"
    ctx.src.branch_sha.return_value = "abc123"
    ctx.dst.branch_sha.return_value = "abc123"

    sync_org(ctx, "src-org", "dst-org", repo_names=["repo1"])

    ctx.src.list_repos.assert_not_called()
