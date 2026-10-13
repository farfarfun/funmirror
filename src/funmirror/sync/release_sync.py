"""Mirror one repo's releases, attachments included, from src to dst.

Runs *after* the git push, never before: a release points at a tag, and
creating one for a tag the destination has never heard of either fails or
silently invents a tag off the wrong commit.

Everything here is idempotent and diff-based. A release already present on
the destination is matched by tag and left alone; an attachment already
present is matched by name and re-uploaded only when its size disagrees.
That matters more than it sounds -- this runs on a schedule, and a pass that
re-uploaded every asset every time would move gigabytes a day to say nothing
changed.
"""

import os
import shutil
import tempfile
from dataclasses import dataclass
from typing import List, Optional

from farlog import get_logger

from funmirror.sync.platforms.base import Platform, Release, ReleaseAsset

logger = get_logger("funmirror")


@dataclass
class ReleaseSyncSummary:
    releases_created: int = 0
    assets_uploaded: int = 0
    releases_checked: int = 0

    def __bool__(self) -> bool:
        """Truthy means something *changed*, not merely that the pass ran."""
        return bool(self.releases_created or self.assets_uploaded)

    def describe(self) -> str:
        bits = []
        if self.releases_created:
            bits.append(f"{self.releases_created} release(s)")
        if self.assets_uploaded:
            bits.append(f"{self.assets_uploaded} asset(s)")
        if bits:
            return ", ".join(bits)
        # Nothing moved -- still worth a word. A bare "up to date" reads
        # identically whether the release pass ran clean or was never
        # switched on, and that is the one thing someone greps this line for.
        if self.releases_checked:
            return f"{self.releases_checked} release(s) already there"
        return ""


def _needs_upload(src: ReleaseAsset, dst: Optional[ReleaseAsset]) -> bool:
    if dst is None:
        return True
    # Sizes are the only cheap content signal either API gives us. When either
    # side won't say, trust the name -- re-uploading on every pass is worse
    # than missing an in-place asset swap, which is rare and recoverable by
    # deleting the attachment on the destination.
    if src.size < 0 or dst.size < 0:
        return False
    return src.size != dst.size


def sync_releases(
    repo: str,
    src_org: str,
    dst_org: str,
    src: Platform,
    dst: Platform,
    *,
    limit: int = 0,
    workdir: Optional[str] = None,
) -> ReleaseSyncSummary:
    """Mirror `repo`'s releases from src_org to dst_org.

    `limit` caps how many of the most recent releases are considered; 0 means
    all of them. Assets are downloaded one at a time and deleted straight
    after upload, so peak disk is one asset, not one release.
    """
    summary = ReleaseSyncSummary()

    releases: List[Release] = src.list_releases(src_org, repo)
    if limit > 0:
        releases = releases[:limit]
    if not releases:
        return summary

    staging = tempfile.mkdtemp(prefix=f"funmirror-rel-{repo}-", dir=workdir)
    try:
        # Oldest first, so an interrupted run leaves the destination with a
        # contiguous prefix of history rather than holes in the middle.
        for release in reversed(releases):
            summary.releases_checked += 1
            release_id, created = dst.ensure_release(dst_org, repo, release)
            if created:
                summary.releases_created += 1
                logger.info(f"{repo}: created release {release.tag} on {dst.name}")
                existing = {}
            else:
                existing = {
                    a.name: a for a in dst.release_assets(dst_org, repo, release_id)
                }

            for asset in release.assets:
                current = existing.get(asset.name)
                if not _needs_upload(asset, current):
                    continue
                local = os.path.join(staging, asset.name)
                try:
                    logger.info(f"{repo}: {release.tag}/{asset.name} -> {dst.name}")
                    src.download_asset(asset, local)
                    if current is not None:
                        dst.delete_asset(dst_org, repo, release_id, current)
                    dst.upload_asset(dst_org, repo, release_id, local)
                    summary.assets_uploaded += 1
                finally:
                    # One asset on disk at a time; CI runners are not roomy.
                    if os.path.exists(local):
                        os.remove(local)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return summary
