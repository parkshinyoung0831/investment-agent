"""긴 읽기·분석 단계가 가격 감시와 승인 처리를 막지 않도록 분리한다."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from investment_agent.operations.harness.contracts import StageOutcome


class BackgroundStages:
    def __init__(self):
        self.executor=ThreadPoolExecutor(max_workers=6,thread_name_prefix='investment-analysis')
        self.pending={}

    def wrap(self, handler):
        def stage(context):
            key=(context.run_id,context.stage_id)
            future=self.pending.get(key)
            if future is None:
                future=self.executor.submit(handler,context)
                self.pending[key]=future
            if not future.done():
                return StageOutcome.waiting(resume_after_seconds=5,metadata={'reason':'background_work_running'})
            del self.pending[key]
            return future.result()
        return stage
