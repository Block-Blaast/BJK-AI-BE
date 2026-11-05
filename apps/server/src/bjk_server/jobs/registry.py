"""구현된 작업을 등록한다. import만으로 runner.REGISTRY가 채워진다."""

from bjk_server.jobs import missed_scan, nightly  # noqa: F401
