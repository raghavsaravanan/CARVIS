"""Alembic environment for the Carvis schema (M2 Track B1).

- The URL comes only from ``CARVIS_MIGRATION_DATABASE_URL`` (never the application URL, never
  ``alembic.ini``), normalized to psycopg 3 like the application setting. It is never printed.
- Online mode only. Each revision runs in its own transaction.
- The version table lives in the CARVIS-owned ``carvis_migrations`` schema, named explicitly, so the
  result never depends on ``search_path``. This environment creates that schema if it is absent,
  after checking that the login may create schemas; a pre-existing one must belong to the login.
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from db.roles import METADATA_SCHEMA, VERSION_TABLE
from settings import MIGRATION_DATABASE_URL_ENV, normalize_database_url


class MigrationConfigurationError(RuntimeError):
    """The migration environment is unusable. Messages name settings and privileges, never values."""


def _engine():
    status, url = normalize_database_url(os.getenv(MIGRATION_DATABASE_URL_ENV))
    if status != "configured" or url is None:
        raise MigrationConfigurationError(f"{MIGRATION_DATABASE_URL_ENV} must be a supported PostgreSQL URL.")
    return create_engine(url.reveal(), poolclass=NullPool, hide_parameters=True,
                         connect_args={"prepare_threshold": None})


def _bootstrap_metadata_schema(connection) -> None:
    owner = connection.execute(text(
        "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = :schema"),
        {"schema": METADATA_SCHEMA}).scalar()
    login, superuser = connection.execute(text(
        "SELECT current_user, rolsuper FROM pg_roles WHERE rolname = current_user")).one()
    if owner is None:
        if not connection.execute(text("SELECT has_database_privilege(current_database(), 'CREATE')")).scalar():
            raise MigrationConfigurationError(
                "The migration login needs CREATE on the database to create the carvis_migrations schema.")
        connection.execute(text(f"CREATE SCHEMA {METADATA_SCHEMA}"))
    elif owner != login and not superuser:
        raise MigrationConfigurationError(
            f"Schema {METADATA_SCHEMA} exists and is not owned by the migration login.")
    connection.commit()


def run_migrations_online() -> None:
    engine = _engine()
    try:
        with engine.connect() as connection:
            _bootstrap_metadata_schema(connection)
            context.configure(
                connection=connection,
                target_metadata=None,
                version_table=VERSION_TABLE,
                version_table_schema=METADATA_SCHEMA,
                transaction_per_migration=True,
            )
            with context.begin_transaction():
                context.run_migrations()
            connection.commit()
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise MigrationConfigurationError("Offline (SQL script) migrations are not supported.")
run_migrations_online()
