"""Org sync: two-phase pipeline.

Phase 1 (detect) runs at high concurrency (`num_detect_workers`) since it's
only cheap commit-id reads -- incremental mode queries just the src platform,
full mode queries both. Only repos phase 1 flags as actually differing move
on to phase 2 (sync): the real clone+push work, at `num_workers` concurrency,
kept low to avoid overwhelming a rate-limited/WAF'd destination like Gitee.
"""

from queue import Queue
from typing import Dict, List, Optional, Tuple

from farlog import get_logger
from funworker import BaseConsumer, BaseProcessor, BaseProducer, Pipeline

from funmirror.sync.platforms.base import RepoRef
from funmirror.sync.repo_sync import DetectResult, SyncContext, SyncResult, detect_repo, sync_repo

logger = get_logger("funmirror")


class ListProducer(BaseProducer):
    def __init__(self, *args, items, **kwargs):
        super().__init__(*args, **kwargs)
        self._iter = iter(items)

    def produce(self):
        return next(self._iter)


class DetectProcessor(BaseProcessor):
    def __init__(
        self,
        src_org: str,
        dst_org: str,
        ctx: SyncContext,
        state: Dict[str, Dict[str, str]],
        incremental: bool,
    ):
        self.src_org = src_org
        self.dst_org = dst_org
        self.ctx = ctx
        self.state = state
        self.incremental = incremental

    def process(self, repo: RepoRef) -> DetectResult:
        return detect_repo(
            repo,
            self.src_org,
            self.dst_org,
            self.ctx,
            state_entry=self.state.get(repo.name),
            incremental=self.incremental,
        )


class DetectConsumer(BaseConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.terminal: List[SyncResult] = []
        self.to_sync: List[Tuple[RepoRef, Optional[str]]] = []

    def consume(self, item: DetectResult) -> None:
        if item.outcome == "sync":
            self.to_sync.append((item.repo, item.src_sha))
        else:
            self.terminal.append(item.result)


class MirrorProcessor(BaseProcessor):
    def __init__(self, src_org: str, dst_org: str, ctx: SyncContext):
        self.src_org = src_org
        self.dst_org = dst_org
        self.ctx = ctx

    def process(self, item: Tuple[RepoRef, Optional[str]]) -> SyncResult:
        repo, src_sha = item
        return sync_repo(repo, self.src_org, self.dst_org, self.ctx, src_sha)


class ResultConsumer(BaseConsumer):
    def __init__(self, *args, total: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.total = total
        self.done = 0
        self.mirrored: List[str] = []
        self.skipped: List[str] = []
        self.failed: List[str] = []
        self.state_updates: Dict[str, Dict[str, str]] = {}

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
            self.state_updates[result.repo] = {
                "src_sha": result.src_sha,
                "dst_sha": result.dst_sha,
            }


def sync_org(
    ctx: SyncContext,
    src_org: str,
    dst_org: str,
    *,
    repo_names: Optional[List[str]] = None,
    num_workers: int = 8,
    num_detect_workers: Optional[int] = None,
    state: Optional[Dict[str, Dict[str, str]]] = None,
    incremental: bool = False,
) -> ResultConsumer:
    """Sync every repo in src_org to dst_org (or just `repo_names`) in two phases.

    `state` maps repo name -> {"src_sha", "dst_sha"} last confirmed in sync.
    See `detect_repo` for exactly what phase 1 checks in incremental vs. full
    mode. Every processed repo's confirmed src/dst shas are returned via
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
    state = state or {}
    detect_workers = num_detect_workers or max(num_workers * 4, 16)

    detect_pipeline = Pipeline.build(
        producer_cls=ListProducer,
        processor=lambda: DetectProcessor(src_org, dst_org, ctx, state, incremental),
        consumer_cls=DetectConsumer,
        num_workers=detect_workers,
        producer_kwargs={"items": repos},
    )
    detect_pipeline.run()
    detected = detect_pipeline.consumer

    if detected.to_sync:
        sync_pipeline = Pipeline.build(
            producer_cls=ListProducer,
            processor=lambda: MirrorProcessor(src_org, dst_org, ctx),
            consumer_cls=ResultConsumer,
            num_workers=num_workers,
            producer_kwargs={"items": detected.to_sync},
            consumer_kwargs={"total": len(repos)},
        )
        sync_pipeline.run()
        consumer = sync_pipeline.consumer
    else:
        consumer = ResultConsumer(input_queue=Queue(), total=len(repos))

    for result in detected.terminal:
        consumer.consume(result)

    return consumer
