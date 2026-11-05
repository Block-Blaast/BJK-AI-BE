"""`make seed`: 개발 환경 DB를 시연 상태로 초기화한다."""

import argparse
import json
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from bjk_server.config import get_settings
from bjk_server.seed.demo import SCENARIOS, seed_demo


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m bjk_server.seed")
    parser.add_argument("--scenario", default="demo_v1", choices=SCENARIOS)
    args = parser.parse_args()

    settings = get_settings()
    if not settings.is_dev:
        print("APP_ENV=dev에서만 시드를 실행할 수 있습니다.", file=sys.stderr)
        return 1
    engine = create_engine(settings.admin_database_url or settings.database_url)
    with Session(engine) as session, session.begin():
        seed_demo(session, args.scenario)
    engine.dispose()
    print(f"seeded: {args.scenario}")
    if args.scenario == "demo_v2":
        # 배치·검토는 RLS가 적용되는 앱 계정으로 돌린다 (jobs CLI와 같다)
        from bjk_server.seed.demo_v2 import finish_demo_v2

        app_engine = create_engine(settings.database_url)
        try:
            print(json.dumps(finish_demo_v2(app_engine), ensure_ascii=False, default=str))
        finally:
            app_engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
