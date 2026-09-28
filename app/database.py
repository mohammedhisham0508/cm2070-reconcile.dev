
import os
from sqlalchemy import (
    create_engine, Column, Integer, Text, String,
    BigInteger, Numeric, Index
)
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/reconcile_dev"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Place(Base):
  
    __tablename__ = "places"

    geonameid    = Column(Integer, primary_key=True, index=True)
    name         = Column(Text, nullable=False)
    asciiname    = Column(Text)
    country_code = Column(String(2), index=True)
    population   = Column(BigInteger, default=0)
    latitude     = Column(Numeric(10, 7))
    longitude    = Column(Numeric(10, 7))

   

def get_db():
   
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
