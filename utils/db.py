from sqlalchemy import create_engine, Column, Date, Integer, String, Numeric, DateTime, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
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

class FintelSout(Base):
    __tablename__ = 'fintel_sout'
    
    id = Column(Integer, primary_key=True)
    scraped_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ticker = Column(String(20), nullable=False)
    security_name = Column(String(500))
    metrics = Column(JSONB) # 存储所有其他列
    data_hash = Column(String(64)) # 数据摘要，用于去重

    __table_args__ = (
        Index('idx_sout_scraped_at', scraped_at.desc()),
        Index('idx_sout_ticker', ticker),
        Index('idx_sout_data_hash', data_hash),
        UniqueConstraint('data_hash', name='uq_sout_data_hash'),
    )

class OptionFlow(Base):
    __tablename__ = 'fintel_option_flow'
    
    id = Column(Integer, primary_key=True)
    scraped_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ticker = Column(String(20), nullable=False)
    security_name = Column(String(500))
    rank = Column(Integer)
    net_premium = Column(Numeric(20, 2))
    put_call_ratio = Column(Numeric(10, 2))

    __table_args__ = (
        Index('idx_option_scraped_at', scraped_at.desc()),
        Index('idx_option_ticker', ticker),
    )

class EarningsEvent(Base):
    __tablename__ = 'earnings_events'

    id = Column(Integer, primary_key=True)
    report_date = Column(Date, nullable=False)
    ticker = Column(String(20), nullable=False)
    exchange = Column(String(50))
    report_time = Column(String(20), nullable=False, default='')
    market_cap = Column(Numeric(20, 2))
    cap_str = Column(String(30))
    source = Column(String(30), nullable=False, default='nasdaq')
    fetched_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('report_date', 'ticker', 'report_time', name='uq_earnings_event'),
        Index('idx_earnings_report_date', report_date),
        Index('idx_earnings_ticker', ticker),
    )

class EarningsCacheDate(Base):
    __tablename__ = 'earnings_cache_dates'

    id = Column(Integer, primary_key=True)
    report_date = Column(Date, nullable=False, unique=True)
    event_count = Column(Integer, nullable=False, default=0)
    fetched_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_earnings_cache_date', report_date),
    )

engine = create_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)
    print("✅ 数据库表已初始化。")

if __name__ == "__main__":
    init_db()
