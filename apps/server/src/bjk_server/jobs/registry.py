"""구현된 작업을 등록한다. import만으로 runner.REGISTRY가 채워진다."""

from bjk_server.jobs import (
    cleanup,  # noqa: F401
    missed_scan,  # noqa: F401
    nightly,  # noqa: F401
    weekly_merge,  # noqa: F401
)
