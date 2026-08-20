"""
database.py
-----------
SQLAlchemy engine and session setup. This is the one place that knows how to
connect to the database; everything else (models, routers) imports from here.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

# check_same_thread=False is SQLite-specific: it allows the connection to be
# used across the multiple threads FastAPI's request handling can involve.
# This flag is silently ignored by other database backends (e.g. Postgres),
# so it's safe to leave in place if database_url changes later.
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Every ORM model (in models.py) inherits from this."""
    pass


def get_db():
    """
    FastAPI dependency: yields one database session per request, and always
    closes it afterward (even if the request raised an error).
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
