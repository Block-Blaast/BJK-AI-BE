from bjk_server.db.models import Part
from bjk_server.jobs.runner import run_job
from bjk_server.seed.perf import measure_chat, seed_perf
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .conftest import DEMO_TODAY


def test_perf_seed_builds_parts_and_measures(demo_db):
    try:
        with Session(demo_db.admin) as s, s.begin():
            names = seed_perf(s, 12, DEMO_TODAY)
        assert len(names) == 6
        with Session(demo_db.admin) as s:
            assert s.scalar(select(func.count()).select_from(Part)) == 12
        result = run_job(demo_db.app, "nightly", "manual")
        assert (result.status, result.summary["parts_computed"]) == ("ok", 12)
        assert len(measure_chat(demo_db.app, names, 3)) == 3
    finally:
        demo_db.reseed()
