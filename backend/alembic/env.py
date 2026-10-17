import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
from app.database import Base
from app.config import settings

target_metadata = Base.metadata

# Set sqlalchemy.url from settings dynamically
db_url = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1) if settings.DATABASE_URL.startswith("postgresql://") else settings.DATABASE_URL
config.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    try:
        import socket, subprocess, sys
        if sys.platform == "darwin":
            out = subprocess.check_output(["ifconfig", "en0"]).decode()
            candidates = [l.strip().split()[1] for l in out.splitlines() if l.strip().startswith("inet6 240")]
            working_ipv6 = None
            for ip in candidates:
                try:
                    s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
                    s.bind((ip, 0))
                    s.settimeout(2)
                    s.connect(("2001:4860:4860::8888", 53))
                    s.close()
                    working_ipv6 = ip
                    break
                except Exception:
                    pass
            if working_ipv6:
                loop = asyncio.get_running_loop()
                orig = loop.create_connection
                async def patched(*args, **kwargs):
                    dest = kwargs.get("host") or (args[1] if len(args) > 1 else "")
                    if dest and "supabase" in str(dest) and kwargs.get("local_addr") is None:
                        kwargs["local_addr"] = (working_ipv6, 0)
                    return await orig(*args, **kwargs)
                loop.create_connection = patched
    except Exception:
        pass

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
