from unittest.mock import Mock

from funmirror.sync.org_sync import sync_org
from funmirror.sync.platforms.base import Platform, RepoRef
from funmirror.sync.repo_sync import SyncContext


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
