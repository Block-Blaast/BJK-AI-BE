import functools
import threading
import time
from datetime import datetime

import pytest
from apscheduler.events import EVENT_JOB_MAX_INSTANCES
from bjk_server.clock import KST
from bjk_server.jobs import scheduler as sched
from bjk_server.jobs.runner import JOB_NAMES, run_job
from sqlalchemy import create_engine

# 연결하지 않는 엔진. 예약·스레드 동작만 본다.
ENGINE = create_engine("postgresql+psycopg://nobody@127.0.0.1:1/none")


@pytest.fixture
def make_scheduler():
    created = []

    def make(workers=2):
        s = sched.build_scheduler(ENGINE, workers)
        created.append(s)
        return s

    yield make
    for s in created:
        if s.running:
            s.shutdown(wait=False)


def _run_now(scheduler, job_id, func):
    scheduler.get_job(job_id).modify(func=func, args=(), kwargs={})
    scheduler.get_job(job_id).modify(next_run_time=datetime.now(KST))


@pytest.mark.parametrize(
    ("job_id", "expected"),
    [
        ("nightly", datetime(2026, 11, 5, 3, 0, tzinfo=KST)),
        ("missed-scan", datetime(2026, 11, 5, 7, 0, tzinfo=KST)),
        ("order-check", datetime(2026, 11, 5, 7, 0, tzinfo=KST)),
        ("briefing", datetime(2026, 11, 5, 7, 30, tzinfo=KST)),
        ("weekly-merge", datetime(2026, 11, 9, 3, 30, tzinfo=KST)),  # 다음 월요일
    ],
)
def test_jobs_follow_spec_times_in_seoul(make_scheduler, job_id, expected):
    job = make_scheduler().get_job(job_id)
    now = datetime(2026, 11, 4, 12, 0, tzinfo=KST)  # 수요일
    assert job.trigger.get_next_fire_time(None, now) == expected


def test_every_job_runs_through_run_job(make_scheduler):
    scheduler = make_scheduler()
    scheduler.start(paused=True)  # 작업 기본값은 시작할 때 적용된다
    assert {j.id for j in scheduler.get_jobs()} == set(JOB_NAMES)
    for job in scheduler.get_jobs():
        assert isinstance(job.func, functools.partial)
        assert job.func.func is run_job
        assert job.func.args == (ENGINE, job.id, "schedule")
        assert (job.max_instances, job.coalesce, job.misfire_grace_time) == (1, True, 1800)


def test_thread_pool_and_db_pool_are_sized_together():
    scheduler = sched.build_scheduler(ENGINE, 3)
    assert scheduler._executors["default"]._pool._max_workers == 3
    engine = sched.create_job_engine("postgresql+psycopg://nobody@127.0.0.1:1/none", 3)
    assert (engine.pool.size(), engine.pool._max_overflow) == (3, 0)


def _concurrent_starts(scheduler, jobs, hold=0.5):
    """jobs를 동시에 깨우고, 같은 순간에 실행 중이던 작업 수의 최대값을 잰다."""
    active, peak, lock = 0, 0, threading.Lock()
    done = threading.Semaphore(0)

    def work():
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(hold)
        with lock:
            active -= 1
        done.release()

    scheduler.start()
    for job_id in jobs:
        _run_now(scheduler, job_id, work)
    for _ in jobs:
        assert done.acquire(timeout=5)
    return peak


def test_two_workers_run_7am_jobs_together(make_scheduler):
    assert _concurrent_starts(make_scheduler(2), ["missed-scan", "order-check"]) == 2


def test_pool_bounds_concurrency(make_scheduler):
    jobs = ["missed-scan", "order-check", "briefing"]
    assert _concurrent_starts(make_scheduler(2), jobs) == 2


def test_same_job_never_overlaps(make_scheduler):
    scheduler = make_scheduler()
    release, started = threading.Event(), threading.Event()
    skipped = []
    scheduler.add_listener(lambda e: skipped.append(e.job_id), EVENT_JOB_MAX_INSTANCES)

    def long_job():
        started.set()
        release.wait(5)

    scheduler.start()
    _run_now(scheduler, "nightly", long_job)
    assert started.wait(5)
    scheduler.get_job("nightly").modify(next_run_time=datetime.now(KST))
    deadline = time.time() + 5
    while not skipped and time.time() < deadline:
        time.sleep(0.05)
    release.set()
    assert skipped == ["nightly"]


def test_serve_waits_for_running_job_before_exit(make_scheduler):
    scheduler = make_scheduler()
    started, finished = threading.Event(), threading.Event()

    def job():
        started.set()
        time.sleep(0.5)
        finished.set()

    stop = threading.Event()
    server = threading.Thread(target=sched.serve, args=(stop, scheduler, ENGINE))
    server.start()
    _run_now(scheduler, "nightly", job)
    assert started.wait(5)
    stop.set()  # 종료 신호
    server.join(5)
    assert not server.is_alive()
    assert finished.is_set()
    assert not scheduler.running
