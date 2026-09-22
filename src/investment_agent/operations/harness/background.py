"""긴 읽기·분석 단계가 가격 감시와 승인 처리를 막지 않도록 분리한다."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from investment_agent.operations.harness.contracts import StageOutcome


class StageTimeoutError(TimeoutError):
    """background stage가 제출 뒤 타임아웃을 넘겨도 끝나지 않았다.

    스레드는 강제로 죽일 수 없어 실제 작업은 백그라운드에서 계속 돈다 — 이 예외는
    스케줄러에게 "더 기다리지 않는다"고만 말한다. 재시도가 새로 제출한 것과 옛 스레드가
    겹칠 수 있으니, 감싸는 handler는 같은 입력을 다시 실행해도 안전해야 한다(대부분
    레코드 단위 upsert라 이미 그렇다).
    """


class BackgroundStages:
    def __init__(self, *, max_workers: int = 6):
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='investment-analysis')
        # key -> (future, 제출 시각). 값은 (run_id, stage_id)별로 하나만 유지한다.
        self.pending: dict[tuple[str, str], tuple] = {}

    def wrap(self, handler, *, timeout_seconds: float | None = None):
        def stage(context):
            key = (context.run_id, context.stage_id)
            # 같은 stage_id의 옛 run 항목이 남아 있으면(잡이 재시작·교체됐다는 뜻) 더 이상
            # 아무도 안 본다 — 누적되게 두지 않는다(감사 OP2-02).
            for stale in [k for k in self.pending if k[1] == context.stage_id and k[0] != context.run_id]:
                del self.pending[stale]
            entry = self.pending.get(key)
            if entry is None:
                future = self.executor.submit(handler, context)
                entry = (future, time.monotonic())
                self.pending[key] = entry
            future, submitted_at = entry
            if not future.done():
                elapsed = time.monotonic() - submitted_at
                if timeout_seconds is not None and elapsed > timeout_seconds:
                    # 제출만 되고 시작도 못 한 채 큐에 갇힌 경우도 여기서 잡힌다 —
                    # worker 부족이 무한 대기가 아니라 눈에 보이는 실패로 드러난다.
                    del self.pending[key]
                    raise StageTimeoutError(
                        f"background stage did not finish within {timeout_seconds:.0f}s "
                        f"(stage_id={context.stage_id})"
                    )
                return StageOutcome.waiting(resume_after_seconds=5, metadata={'reason': 'background_work_running'})
            del self.pending[key]
            return future.result()
        return stage
