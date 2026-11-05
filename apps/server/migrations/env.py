from logging.config import fileConfig

from alembic import context
from bjk_server.config import get_settings
from bjk_server.db.models import Base
from sqlalchemy import engine_from_config, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# 테스트는 config에 URL을 직접 넣는다. 그 외에는 소유자 계정으로 마이그레이션한다.
if not config.get_main_option("sqlalchemy.url"):
    settings = get_settings()
    config.set_main_option("sqlalchemy.url", settings.admin_database_url or settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
