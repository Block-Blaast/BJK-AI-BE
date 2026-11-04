"""배치 실행기.

- 작업 함수는 소유자 계정 세션(회사 전체 대상)과 기준 시각을 받아 요약(dict)을 돌려준다.
- 같은 작업이 동시에 돌지 않도록 트랜잭션 advisory lock을 잡는다. 못 잡으면 건너뛴다.
- 작업이 실패하면 작업 트랜잭션은 롤백하고 실패 기록만 따로 남긴다.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, get_args

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from bjk_server import clock
from bjk_server.db.models import JobRun

JobName = Literal["nightly", "missed-scan", "order-check", "briefing", "weekly-merge"]
JOB_NAMES: tuple[str, ...] = get_args(JobName)
Trigger = Literal["schedule", "manual"]
JobFunc = Callable[[Session, datetime], dict[str, Any]]

# 작업 이름 → 함수. 아직 구현하지 않은 작업은 실행 시 skipped로 기록한다.
REGISTRY: dict[str, JobFunc] = {}


def job(name: JobName) -> Callable[[JobFunc], JobFunc]:
    def register(fn: JobFunc) -> JobFunc:
        REGISTRY[name] = fn
        return fn

    return register


class _AlreadyRunning(Exception):
    pass


@dataclass(frozen=True)
class RunResult:
    id: Any
    name: str
    status: Literal["ok", "error", "skipped"]
    started_at: datetime
    finished_at: datetime
    summary: dict[str, Any]
    error: str | None = None


def run_job(engine: Engine, name: str, trigger: Trigger, now: datetime | None = None) -> RunResult:
    if name not in JOB_NAMES:
        raise ValueError(f"unknown job: {name}")
    started = now or clock.utcnow()
    status, summary, error = "ok", {}, None
    fn = REGISTRY.get(name)
    if fn is None:
        status, summary = "skipped", {"reason": "not_implemented"}
    else:
        try:
            with Session(engine) as session, session.begin():
                locked = session.scalar(
                    select(func.pg_try_advisory_xact_lock(func.hashtext(f"job:{name}")))
                )
                if not locked:
                    raise _AlreadyRunning
                summary = fn(session, started)
        except _AlreadyRunning:
            status, summary = "skipped", {"reason": "already_running"}
        except Exception as exc:  # noqa: BLE001 - 실패도 실행 기록으로 남긴다
            status, error = "error", f"{type(exc).__name__}: {exc}"[:2000]

    finished = clock.utcnow() if now is None else now
    with Session(engine) as session, session.begin():
        run = JobRun(
            name=name,
            trigger=trigger,
            status=status,
            started_at=started,
            finished_at=finished,
            summary=summary,
            error=error,
        )
        session.add(run)
        session.flush()
        run_id = run.id
    return RunResult(run_id, name, status, started, finished, summary, error)
