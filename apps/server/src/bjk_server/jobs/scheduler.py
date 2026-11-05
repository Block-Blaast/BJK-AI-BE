"""배치 예약 스케줄러 (기능명세서 2장 기술 스택: APScheduler).

API 서버와 분리된 프로세스로 띄운다: python -m bjk_server.jobs.scheduler
예약은 이 모듈이 하고 실행·잠금·기록은 runner.run_job이 그대로 맡는다.

스레드 풀 기준
- 워커 수(scheduler_workers, 기본 2): 같은 시각에 겹치는 작업이 최대 2개다.
  07:00 missed-scan·order-check, 그리고 nightly가 길어지면 월요일 03:30 weekly-merge.
  더 늘리면 DB 연결만 더 쓴다.
- DB 연결 풀 = 워커 수, overflow 0: run_job은 작업 하나에 연결을 하나씩만(작업 → 기록 순서로) 쓰므로
  워커가 연결을 기다리며 멈추지 않는다. 연결을 더 쓰는 작업이 생기면 이 값을 함께 늘린다.
- 같은 작업은 1개만(max_instances=1), 밀린 실행은 1회로 합치고(coalesce), 30분 넘게 늦으면 건너뛴다.
  다른 프로세스(CLI, DEV-01)와의 중복은 run_job의 advisory lock이 막는다.
- 종료 신호(SIGTERM·SIGINT)를 받으면 새 실행을 멈추고 실행 중인 작업이 끝날 때까지 기다린다.
  기다리다 강제 종료되면 작업 트랜잭션은 롤백되어 반쯤 쓴 결과가 남지 않는다.
"""

import functools
import logging
import signal
import threading
from typing import Any

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_MAX_INSTANCES,
    EVENT_JOB_MISSED,
    JobEvent,
)
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import Engine, create_engine

from bjk_server.clock import KST
from bjk_server.config import get_settings
from bjk_server.jobs import registry  # noqa: F401 - 작업 등록
from bjk_server.jobs.runner import JobName, run_job

log = logging.getLogger("bjk_server.scheduler")

# API 명세서 14장. 시각은 Asia/Seoul.
SCHEDULE: dict[JobName, dict[str, Any]] = {
    "nightly": {"hour": 3, "minute": 0},
    "missed-scan": {"hour": 7, "minute": 0},
    "order-check": {"hour": 7, "minute": 0},
    "briefing": {"hour": 7, "minute": 30},
    "weekly-merge": {"day_of_week": "mon", "hour": 3, "minute": 30},
    "cleanup": {"hour": 4, "minute": 0},
    # 조용한 시간으로 미룬 웹 푸시 (NOT-04)
    "push": {"minute": "*/10"},
}
MISFIRE_GRACE_SECONDS = 30 * 60


def create_job_engine(url: str, workers: int) -> Engine:
    """스케줄러 전용 엔진. 연결 풀을 워커 수에 맞춰 묶는다."""
    return create_engine(
        url, pool_size=workers, max_overflow=0, pool_timeout=30, pool_pre_ping=True
    )


def build_scheduler(engine: Engine, workers: int) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(
        executors={"default": ThreadPoolExecutor(max_workers=workers)},
        job_defaults={
            "max_instances": 1,
            "coalesce": True,
            "misfire_grace_time": MISFIRE_GRACE_SECONDS,
        },
        timezone=KST,
    )
    for name, fields in SCHEDULE.items():
        scheduler.add_job(
            functools.partial(run_job, engine, name, "schedule"),
            CronTrigger(timezone=KST, **fields),
            id=name,
            name=name,
            replace_existing=True,
        )
    scheduler.add_listener(_log_event, EVENT_JOB_MISSED | EVENT_JOB_MAX_INSTANCES | EVENT_JOB_ERROR)
    return scheduler


def _log_event(event: JobEvent) -> None:
    if event.code == EVENT_JOB_MISSED:
        log.warning("job %s missed its run at %s", event.job_id, event.scheduled_run_time)
    elif event.code == EVENT_JOB_MAX_INSTANCES:
        log.warning(
            "job %s is still running; skipped run at %s", event.job_id, event.scheduled_run_time
        )
    else:
        log.error("job %s raised outside run_job", event.job_id, exc_info=event.exception)


def serve(stop: threading.Event, scheduler: BackgroundScheduler, engine: Engine) -> None:
    """stop이 설정될 때까지 예약을 돌리고, 실행 중인 작업을 기다린 뒤 끝낸다."""
    scheduler.start()
    log.info("scheduler started: %d jobs", len(scheduler.get_jobs()))
    try:
        stop.wait()
    finally:
        log.info("scheduler stopping: waiting for running jobs")
        scheduler.shutdown(wait=True)
        engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    workers = settings.scheduler_workers
    # 배치는 RLS가 적용되는 앱 계정으로 실행한다.
    engine = create_job_engine(settings.database_url, workers)
    serve(stop, build_scheduler(engine, workers), engine)


if __name__ == "__main__":
    main()
