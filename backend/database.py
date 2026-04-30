from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

# Crear directorio data si no existe (usa /data en Render, local fallback)
_db_dir = os.getenv("DB_DIR", "/data")
os.makedirs(_db_dir, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{_db_dir}/trading_bot.db")

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
