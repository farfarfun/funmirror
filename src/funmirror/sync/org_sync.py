"""Org sync: list repos on the source platform, fan out into N repo-sync tasks
via funworker's producer/processor/consumer pipeline."""

from typing import Dict, List, Optional

from farlog import get_logger
from funworker import BaseConsumer, BaseProcessor, BaseProducer, Pipeline

from funmirror.sync.platforms.base import RepoRef
from funmirror.sync.repo_sync import SyncContext, SyncResult, sync_repo

logger = get_logger("funmirror")


class RepoProducer(BaseProducer):
    def __init__(self, *args, repos: List[RepoRef], **kwargs):
        super().__init__(*args, **kwargs)
        self._iter = iter(repos)

    def produce(self):
        return next(self._iter)


class SyncProcessor(BaseProcessor):
    def __init__(
        self,
        src_org: str,
        dst_org: str,
        ctx: SyncContext,
        state: Dict[str, str],
        incremental: bool,
    ):
        self.src_org = src_org
        self.dst_org = dst_org
        self.ctx = ctx
        self.state = state
        self.incremental = incremental

    def process(self, repo: RepoRef) -> SyncResult:
        return sync_repo(
            repo,
            self.src_org,
            self.dst_org,
            self.ctx,
            state_sha=self.state.get(repo.name),
            incremental=self.incremental,
        )


class ResultConsumer(BaseConsumer):
    def __init__(self, *args, total: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.total = total
        self.done = 0
        self.mirrored: List[str] = []
        self.skipped: List[str] = []
        self.failed: List[str] = []
        self.state_updates: Dict[str, str] = {}

    def consume(self, result: SyncResult) -> None:
        self.done += 1
        detail = f" ({result.detail})" if result.detail else ""
        logger.info(
            f"[{self.done}/{self.total}] {result.repo}: {result.status}{detail}"
        )
        bucket = {
            "mirrored": self.mirrored,
            "skipped": self.skipped,
            "failed": self.failed,
        }
        bucket[result.status].append(result.repo)
        if result.status != "failed" and result.src_sha:
            self.state_updates[result.repo] = result.src_sha


def sync_org(
    ctx: SyncContext,
    src_org: str,
    dst_org: str,
    *,
    repo_names: Optional[List[str]] = None,
    num_workers: int = 8,
    state: Optional[Dict[str, str]] = None,
    incremental: bool = False,
) -> ResultConsumer:
    """Sync every repo in src_org to dst_org in parallel (or just `repo_names`).

    `state` maps repo name -> last-known-good src branch sha. When `incremental`
    is set, a repo whose current src sha still matches `state` is skipped
    without ever querying the destination platform. Regardless of `incremental`,
    every processed repo's confirmed src sha is returned via
    `ResultConsumer.state_updates`, so callers can persist a fresh baseline.
    """
    repos = (
        [
            RepoRef(name, ctx.src.default_branch(src_org, name) or "master")
            for name in repo_names
        ]
        if repo_names
        else ctx.src.list_repos(src_org)
    )

    pipeline = Pipeline.build(
        producer_cls=RepoProducer,
        processor=lambda: SyncProcessor(src_org, dst_org, ctx, state or {}, incremental),
        consumer_cls=ResultConsumer,
        num_workers=num_workers,
        producer_kwargs={"repos": repos},
        consumer_kwargs={"total": len(repos)},
    )
    pipeline.run()
    return pipeline.consumer
