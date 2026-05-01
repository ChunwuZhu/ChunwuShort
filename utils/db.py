from sqlalchemy import create_engine, Column, Integer, String, Numeric, DateTime, Index, func
from sqlalchemy.orm import declarative_base, sessionmaker
from utils.config import config

Base = declarative_base()

class ShortSqueeze(Base):
    __tablename__ = 'fintel_short_squeeze'
    
    id = Column(Integer, primary_key=True)
    scraped_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ticker = Column(String(20), nullable=False)
    security_name = Column(String(500))
    rank = Column(Integer)
    score = Column(Numeric(10, 2))
    borrow_fee_rate = Column(Numeric(10, 2))
    short_float_pct = Column(Numeric(10, 2))
    si_change_1m_pct = Column(Numeric(10, 2))

    __table_args__ = (
        Index('idx_short_scraped_at', scraped_at.desc()),
        Index('idx_short_ticker', ticker),
    )

class GammaSqueeze(Base):
    __tablename__ = 'fintel_gamma_squeeze'
    
    id = Column(Integer, primary_key=True)
    scraped_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ticker = Column(String(20), nullable=False)
    security_name = Column(String(500))
    rank = Column(Integer)
    score = Column(Numeric(10, 2))
    gex_mm = Column(Numeric(15, 2))
    put_call_ratio = Column(Numeric(10, 2))
    price_momo_1w_pct = Column(Numeric(10, 2))

    __table_args__ = (
        Index('idx_gamma_scraped_at', scraped_at.desc()),
        Index('idx_gamma_ticker', ticker),
    )

engine = create_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)
    print("✅ 数据库表已初始化。")

if __name__ == "__main__":
    init_db()
