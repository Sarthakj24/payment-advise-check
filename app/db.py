import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# DATABASE_URL is supplied by the hosting environment (e.g. Render Postgres).
# Falls back to a local SQLite file for development when unset.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./payroll.db")

# Render/Heroku hand out "postgres://" URLs, but SQLAlchemy 2.x requires the
# "postgresql://" scheme. Normalise so either form works.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL, connect_args={"check_same_thread": False}
    )
else:
    # pool_pre_ping recycles connections dropped by the Postgres server so the
    # app survives idle periods / restarts without stale-connection errors.
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
