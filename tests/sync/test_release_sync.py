import os
from unittest.mock import Mock

from funmirror.sync.platforms.base import Platform, Release, ReleaseAsset
from funmirror.sync.release_sync import sync_releases


def _src(releases):
    src = Mock(spec=Platform)
    src.name = "github"
    src.list_releases.return_value = releases
    src.download_asset.side_effect = lambda asset, dest: open(dest, "wb").write(b"x")
    return src


def _dst(release_id="42", created=True, existing=()):
    dst = Mock(spec=Platform)
    dst.name = "gitee"
    dst.ensure_release.return_value = (release_id, created)
    dst.release_assets.return_value = list(existing)
    return dst


def test_no_releases_does_nothing():
    src, dst = _src([]), _dst()

    summary = sync_releases("repo1", "src-org", "dst-org", src, dst)

    assert not summary
    dst.ensure_release.assert_not_called()


def test_creates_release_and_uploads_every_asset():
    src = _src(
        [Release(tag="v1", assets=[ReleaseAsset("a.tar.gz", 10), ReleaseAsset("b.deb", 20)])]
    )
    dst = _dst(created=True)

    summary = sync_releases("repo1", "src-org", "dst-org", src, dst)

    assert summary.releases_created == 1
    assert summary.assets_uploaded == 2
    # Nothing can already be attached to a release we just created -- asking
    # is a wasted round trip against a WAF'd API.
    dst.release_assets.assert_not_called()


def test_skips_assets_already_there_with_the_same_size():
    src = _src([Release(tag="v1", assets=[ReleaseAsset("a.tar.gz", 10)])])
    dst = _dst(created=False, existing=[ReleaseAsset("a.tar.gz", 10, id="7")])

    summary = sync_releases("repo1", "src-org", "dst-org", src, dst)

    assert summary.assets_uploaded == 0
    dst.upload_asset.assert_not_called()
    src.download_asset.assert_not_called()


def test_replaces_an_asset_whose_size_changed():
    src = _src([Release(tag="v1", assets=[ReleaseAsset("a.tar.gz", 99)])])
    dst = _dst(created=False, existing=[ReleaseAsset("a.tar.gz", 10, id="7")])

    summary = sync_releases("repo1", "src-org", "dst-org", src, dst)

    assert summary.assets_uploaded == 1
    # Gitee has no overwrite: the stale attachment has to go first, or the
    # release ends up with two files of the same name.
    dst.delete_asset.assert_called_once()
    assert dst.delete_asset.call_args[0][3].id == "7"


def test_unknown_size_falls_back_to_matching_on_name():
    """Re-uploading every asset on every scheduled run is a worse failure
    than missing an in-place swap, so an unknown size means "leave it"."""
    src = _src([Release(tag="v1", assets=[ReleaseAsset("a.tar.gz", -1)])])
    dst = _dst(created=False, existing=[ReleaseAsset("a.tar.gz", 10, id="7")])

    summary = sync_releases("repo1", "src-org", "dst-org", src, dst)

    assert summary.assets_uploaded == 0


def test_release_limit_keeps_the_most_recent():
    src = _src([Release(tag=f"v{i}") for i in range(5)])
    dst = _dst(created=True)

    sync_releases("repo1", "src-org", "dst-org", src, dst, limit=2)

    # list_releases is newest-first; oldest-first on the way out so an
    # interrupted run leaves a contiguous prefix of history.
    assert [c[0][2].tag for c in dst.ensure_release.call_args_list] == ["v1", "v0"]


def test_uploads_oldest_release_first():
    src = _src([Release(tag="v3"), Release(tag="v2"), Release(tag="v1")])
    dst = _dst(created=True)

    sync_releases("repo1", "src-org", "dst-org", src, dst)

    assert [c[0][2].tag for c in dst.ensure_release.call_args_list] == ["v1", "v2", "v3"]


def test_local_copy_is_removed_after_upload(tmp_path):
    src = _src([Release(tag="v1", assets=[ReleaseAsset("big.bin", 10)])])
    dst = _dst(created=True)
    staged = []
    dst.upload_asset.side_effect = lambda *a: staged.append(a[3])

    sync_releases("repo1", "src-org", "dst-org", src, dst, workdir=str(tmp_path))

    # Peak disk is one asset, not one release: CI runners are not roomy.
    assert staged and not any(os.path.exists(p) for p in staged)
