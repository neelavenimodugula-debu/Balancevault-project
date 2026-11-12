from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from ledgerline.config import get_settings


class Base(DeclarativeBase):
    pass


def get_engine(url: str | None = None):
    db_url = url or get_settings().database_url
    if db_url.startswith("sqlite"):
        if ":memory:" in db_url:
            return create_engine(
                db_url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        return create_engine(
            db_url,
            connect_args={"check_same_thread": False},
        )
    return create_engine(db_url, pool_pre_ping=True)


engine = get_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Generator[Session]:
    with SessionLocal() as session:
        yield session
