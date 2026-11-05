"""플랫폼 cron용 CLI: python -m bjk_server.jobs <name>

예약 시각(Asia/Seoul)은 infra/cron/crontab 참고. 실패하면 종료 코드 1.
"""

import argparse
import json
import sys

from sqlalchemy import create_engine

from bjk_server.config import get_settings
from bjk_server.jobs import registry  # noqa: F401 - 작업 등록
from bjk_server.jobs.runner import JOB_NAMES, run_job


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bjk_server.jobs")
    parser.add_argument("name", choices=JOB_NAMES)
    args = parser.parse_args(argv)

    settings = get_settings()
    # 배치는 RLS가 적용되는 앱 계정으로 실행한다.
    engine = create_engine(settings.database_url)
    try:
        result = run_job(engine, args.name, "schedule")
    finally:
        engine.dispose()
    print(json.dumps({"job": result.name, "status": result.status, **result.summary}, default=str))
    return 1 if result.status == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
