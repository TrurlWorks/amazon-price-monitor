from alembic import context

from backend import models  # noqa: F401 -- register domain metadata
from backend.config import Settings
from backend.database import Base, create_database

if context.is_offline_mode():
    context.configure(
        url="sqlite://",
        target_metadata=Base.metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_database(Settings())
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=Base.metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
