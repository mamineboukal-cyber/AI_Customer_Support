"""Alembic environment.

Builds its own connection from the DATABASE_* variables in .env. It does not use
app.embeddings.embedding.get_conn(): that registers the pgvector type, which fails on
an empty database before the first migration has created the extension (and it would
also load the embedding model just to run a migration).

There are no SQLAlchemy models (the app uses raw psycopg), so target_metadata is None
and migrations are written by hand; autogenerate is not used.
"""
import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import URL, create_engine, pool

load_dotenv()

config = context.config
# A caller (the test suite) can hand over its own connection through
# config.attributes["connection"]; then logging is left alone and .env is not used.
external_connection = config.attributes.get("connection")
if config.config_file_name is not None and external_connection is None:
    fileConfig(config.config_file_name)

target_metadata = None


def database_url():
    # URL.create escapes the password itself; putting a URL string into alembic.ini
    # would break on passwords containing '%' (configparser interpolation) or '@'.
    return URL.create(
        "postgresql+psycopg",
        username=os.getenv("DATABASE_USER"),
        password=os.getenv("DATABASE_PASSWORD"),
        host=os.getenv("DATABASE_HOST"),
        port=int(os.getenv("DATABASE_PORT")),
        database=os.getenv("DATABASE_NAME"),
    )


def run_migrations_offline():
    """`alembic upgrade head --sql`: print the SQL, needs only the dialect, no credentials."""
    context.configure(
        url=URL.create("postgresql+psycopg"),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    if external_connection is not None:
        context.configure(connection=external_connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        # Postgres has transactional DDL: a failing migration rolls back completely.
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
