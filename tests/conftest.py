from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from ledgerline.config import get_settings
from ledgerline.database import Base, get_session
from ledgerline.main import app


@pytest.fixture(scope="session", autouse=True)
def test_engine():
    get_settings().environment = "testing"
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    import ledgerline.database as db_mod
    db_mod.engine = engine
    db_mod.SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return engine


@pytest.fixture(scope="function")
def db_session(test_engine) -> Generator[Session]:
    TestingSessionLocal = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(scope="function")
def client(db_session: Session) -> Generator[TestClient]:
    def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()

