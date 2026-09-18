"""Parallel repo mirroring built on funworker's producer/processor/consumer pipeline."""

from typing import Dict, List

from farlog import get_logger
from funworker import BaseConsumer, BaseProcessor, BaseProducer, Pipeline

from funmirror.sync.mirror import MirrorContext, MirrorResult, mirror_one

logger = get_logger("funmirror")


class RepoProducer(BaseProducer):
    def __init__(self, *args, repos: List[Dict], **kwargs):
        super().__init__(*args, **kwargs)
        self._iter = iter(repos)

    def produce(self):
        return next(self._iter)


class MirrorProcessor(BaseProcessor):
    def __init__(self, ctx: MirrorContext):
        self.ctx = ctx

    def process(self, repo: Dict) -> MirrorResult:
        return mirror_one(repo, self.ctx)


class ResultConsumer(BaseConsumer):
    def __init__(self, *args, total: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.total = total
        self.done = 0
        self.mirrored: List[str] = []
        self.skipped: List[str] = []
        self.failed: List[str] = []

    def consume(self, result: MirrorResult) -> None:
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


def run_mirror(
    repos: List[Dict], ctx: MirrorContext, *, num_workers: int = 8
) -> ResultConsumer:
    """Mirror `repos` in parallel and return the consumer holding the final tallies."""
    pipeline = Pipeline.build(
        producer_cls=RepoProducer,
        processor=lambda: MirrorProcessor(ctx),
        consumer_cls=ResultConsumer,
        num_workers=num_workers,
        producer_kwargs={"repos": repos},
        consumer_kwargs={"total": len(repos)},
    )
    pipeline.run()
    return pipeline.consumer
