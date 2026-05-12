from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    Index,
)
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

class QCEarningsSyncRun(Base):
    __tablename__ = 'qc_earnings_sync_runs'

    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at = Column(DateTime(timezone=True))
    run_date = Column(Date, nullable=False)
    requested_start_date = Column(Date, nullable=False)
    requested_end_date = Column(Date, nullable=False)
    source = Column(String(100), nullable=False, default='quantconnect')
    status = Column(String(40), nullable=False, default='running')
    raw_event_count = Column(Integer, nullable=False, default=0)
    fundamental_count = Column(Integer, nullable=False, default=0)
    eligible_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text)

    __table_args__ = (
        Index('idx_qc_earnings_sync_run_date', run_date.desc()),
        Index('idx_qc_earnings_sync_status', status),
    )

class QCEarningsRawEvent(Base):
    __tablename__ = 'qc_earnings_raw_events'

    id = Column(Integer, primary_key=True)
    sync_run_id = Column(Integer, ForeignKey('qc_earnings_sync_runs.id'), nullable=False)
    as_of_date = Column(Date, nullable=False)
    ticker = Column(String(20), nullable=False)
    report_date = Column(Date, nullable=False)
    report_time = Column(String(40))
    eps_estimate = Column(Numeric(20, 6))
    source_payload = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('sync_run_id', 'ticker', 'report_date', 'report_time', name='uq_qc_raw_earnings_event'),
        Index('idx_qc_raw_earnings_report_date', report_date),
        Index('idx_qc_raw_earnings_ticker', ticker),
    )

class QCFundamentalSnapshot(Base):
    __tablename__ = 'qc_fundamental_snapshots'

    id = Column(Integer, primary_key=True)
    sync_run_id = Column(Integer, ForeignKey('qc_earnings_sync_runs.id'), nullable=False)
    ticker = Column(String(20), nullable=False)
    snapshot_date = Column(Date, nullable=False)
    company_name = Column(String(500))
    market_cap = Column(Numeric(24, 2))
    sector_code = Column(String(100))
    industry_group_code = Column(String(100))
    industry_code = Column(String(100))
    exchange_id = Column(String(50))
    country_id = Column(String(50))
    currency_id = Column(String(20))
    shares_outstanding = Column(Numeric(24, 4))
    revenue_ttm = Column(Numeric(24, 4))
    gross_profit_ttm = Column(Numeric(24, 4))
    operating_income_ttm = Column(Numeric(24, 4))
    net_income_ttm = Column(Numeric(24, 4))
    eps_ttm = Column(Numeric(20, 6))
    pe_ratio = Column(Numeric(20, 6))
    forward_pe_ratio = Column(Numeric(20, 6))
    pb_ratio = Column(Numeric(20, 6))
    ps_ratio = Column(Numeric(20, 6))
    pcf_ratio = Column(Numeric(20, 6))
    ev_to_ebitda = Column(Numeric(20, 6))
    ev_to_revenue = Column(Numeric(20, 6))
    roe = Column(Numeric(20, 6))
    roa = Column(Numeric(20, 6))
    current_ratio = Column(Numeric(20, 6))
    quick_ratio = Column(Numeric(20, 6))
    gross_margin = Column(Numeric(20, 6))
    net_margin = Column(Numeric(20, 6))
    fundamental_json = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('sync_run_id', 'ticker', name='uq_qc_fundamental_snapshot_run_ticker'),
        Index('idx_qc_fundamental_snapshot_date', snapshot_date.desc()),
        Index('idx_qc_fundamental_ticker', ticker),
    )

class QCEarningsCurrentEvent(Base):
    __tablename__ = 'qc_earnings_current_events'

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), nullable=False)
    company_name = Column(String(500))
    report_date = Column(Date, nullable=False)
    report_time = Column(String(40))
    eps_estimate = Column(Numeric(20, 6))
    market_cap = Column(Numeric(24, 2))
    exchange_id = Column(String(50))
    sector_code = Column(String(100))
    industry_code = Column(String(100))
    first_seen_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_sync_run_id = Column(Integer, ForeignKey('qc_earnings_sync_runs.id'))
    seen_count = Column(Integer, nullable=False, default=1)
    missing_count = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    inactive_reason = Column(String(100))
    is_eligible = Column(Boolean, nullable=False, default=False)
    eligibility_reason = Column(String(200))
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_qc_current_earnings_ticker_active', ticker, is_active),
        Index('idx_qc_current_earnings_report_date', report_date),
        Index('idx_qc_current_earnings_eligible', is_eligible, is_active),
    )

class QCEarningsEventChange(Base):
    __tablename__ = 'qc_earnings_event_changes'

    id = Column(Integer, primary_key=True)
    current_event_id = Column(Integer, ForeignKey('qc_earnings_current_events.id'), nullable=False)
    ticker = Column(String(20), nullable=False)
    field_name = Column(String(100), nullable=False)
    old_value = Column(Text)
    new_value = Column(Text)
    sync_run_id = Column(Integer, ForeignKey('qc_earnings_sync_runs.id'), nullable=False)
    changed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_qc_earnings_change_event', current_event_id),
        Index('idx_qc_earnings_change_ticker', ticker),
    )

class EarningsWatchlist(Base):
    __tablename__ = 'earnings_watchlist'

    id = Column(Integer, primary_key=True)
    current_event_id = Column(Integer, ForeignKey('qc_earnings_current_events.id'), nullable=False)
    ticker = Column(String(20), nullable=False)
    status = Column(String(40), nullable=False, default='watching')
    selected_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    selected_reason = Column(String(300))
    analysis_start_date = Column(Date)
    report_date = Column(Date)
    report_time = Column(String(40))
    market_cap = Column(Numeric(24, 2))
    last_fundamental_snapshot_id = Column(Integer, ForeignKey('qc_fundamental_snapshots.id'))
    notes = Column(Text)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_earnings_watchlist_ticker_status', ticker, status),
        Index('idx_earnings_watchlist_report_date', report_date),
    )

class DataJob(Base):
    __tablename__ = 'data_jobs'

    id = Column(Integer, primary_key=True)
    job_type = Column(String(100), nullable=False)
    ticker = Column(String(20))
    status = Column(String(40), nullable=False, default='pending')
    priority = Column(Integer, nullable=False, default=100)
    params = Column(JSONB)
    result = Column(JSONB)
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))

    __table_args__ = (
        Index('idx_data_jobs_status_priority', status, priority, created_at),
        Index('idx_data_jobs_ticker', ticker),
    )

class OptionChainDownload(Base):
    __tablename__ = 'option_chain_downloads'

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), nullable=False)
    trade_date = Column(Date, nullable=False)
    window_id = Column(String(100))
    source = Column(String(100), nullable=False, default='quantconnect')
    resolution = Column(String(40), nullable=False, default='minute')
    filter_preset = Column(String(100), nullable=False, default='earnings_wide_v1')
    min_dte = Column(Integer, nullable=False, default=0)
    max_dte = Column(Integer, nullable=False, default=180)
    min_strike_rank = Column(Integer, nullable=False, default=-250)
    max_strike_rank = Column(Integer, nullable=False, default=250)
    path = Column(Text)
    contract_count = Column(Integer)
    row_count = Column(Integer)
    file_size = Column(Integer)
    status = Column(String(40), nullable=False, default='pending')
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            'ticker',
            'trade_date',
            'filter_preset',
            'min_dte',
            'max_dte',
            'min_strike_rank',
            'max_strike_rank',
            name='uq_option_chain_download_scope',
        ),
        Index('idx_option_chain_download_ticker_date', ticker, trade_date),
        Index('idx_option_chain_download_status', status),
    )

class EquityPriceDownload(Base):
    __tablename__ = 'equity_price_downloads'

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), nullable=False)
    resolution = Column(String(40), nullable=False)
    window_id = Column(String(100))
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    source = Column(String(100), nullable=False, default='quantconnect')
    path = Column(Text)
    row_count = Column(Integer)
    file_size = Column(Integer)
    status = Column(String(40), nullable=False, default='pending')
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            'ticker',
            'resolution',
            'window_id',
            'start_date',
            'end_date',
            name='uq_equity_price_download_scope',
        ),
        Index('idx_equity_price_download_ticker_resolution', ticker, resolution),
        Index('idx_equity_price_download_status', status),
    )

class EquityTechnicalSummary(Base):
    __tablename__ = 'equity_technical_summaries'

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), nullable=False)
    window_id = Column(String(100), nullable=False)
    report_date = Column(Date, nullable=False)
    as_of_date = Column(Date, nullable=False)
    daily_start_date = Column(Date)
    daily_end_date = Column(Date)
    minute_start_date = Column(Date)
    minute_end_date = Column(Date)
    trend_regime = Column(String(40))
    momentum_regime = Column(String(40))
    volatility_regime = Column(String(40))
    volume_regime = Column(String(40))
    close_price = Column(Numeric(20, 6))
    return_5d_pct = Column(Numeric(20, 6))
    return_20d_pct = Column(Numeric(20, 6))
    return_60d_pct = Column(Numeric(20, 6))
    rsi_14 = Column(Numeric(20, 6))
    atr_14_pct = Column(Numeric(20, 6))
    hv_20 = Column(Numeric(20, 6))
    hv_60 = Column(Numeric(20, 6))
    distance_to_52w_high_pct = Column(Numeric(20, 6))
    distance_to_52w_low_pct = Column(Numeric(20, 6))
    above_sma_20 = Column(Boolean)
    above_sma_50 = Column(Boolean)
    above_sma_200 = Column(Boolean)
    latest_close_vs_vwap_pct = Column(Numeric(20, 6))
    summary_json = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('ticker', 'window_id', 'as_of_date', name='uq_equity_technical_summary_scope'),
        Index('idx_equity_technical_summary_ticker_report', ticker, report_date),
        Index('idx_equity_technical_summary_as_of', as_of_date.desc()),
    )

class HistoricalEarningsEvent(Base):
    __tablename__ = 'historical_earnings_events'

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), nullable=False)
    report_date = Column(Date, nullable=False)
    qc_observed_date = Column(Date)
    qc_file_date = Column(Date)
    period_ending_date = Column(Date)
    basic_eps_3m = Column(Numeric(20, 6))
    diluted_eps_3m = Column(Numeric(20, 6))
    sec_cik = Column(String(20))
    sec_acceptance_datetime = Column(DateTime(timezone=True))
    sec_form_type = Column(String(40))
    sec_accession_number = Column(String(80))
    sec_primary_document = Column(String(300))
    sec_items = Column(String(200))
    release_session = Column(String(40), nullable=False, default='unknown')
    release_time_confidence = Column(String(40), nullable=False, default='low')
    source_priority = Column(String(100), nullable=False, default='qc_sec')
    source_url = Column(Text)
    source_payload = Column(JSONB)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('ticker', 'report_date', 'period_ending_date', name='uq_historical_earnings_event'),
        Index('idx_historical_earnings_ticker_date', ticker, report_date),
        Index('idx_historical_earnings_session', release_session),
    )

class EarningsDataReadiness(Base):
    __tablename__ = 'earnings_data_readiness'

    id = Column(Integer, primary_key=True)
    current_event_id = Column(Integer, ForeignKey('qc_earnings_current_events.id'), nullable=False)
    ticker = Column(String(20), nullable=False)
    report_date = Column(Date, nullable=False)
    status = Column(String(40), nullable=False)
    required_missing_count = Column(Integer, nullable=False, default=0)
    optional_missing_count = Column(Integer, nullable=False, default=0)
    required_ready = Column(Boolean, nullable=False, default=False)
    optional_context_ready = Column(Boolean, nullable=False, default=False)
    latest_fundamental_snapshot_id = Column(Integer, ForeignKey('qc_fundamental_snapshots.id'))
    technical_summary_id = Column(Integer, ForeignKey('equity_technical_summaries.id'))
    benchmark_spy_summary_id = Column(Integer, ForeignKey('equity_technical_summaries.id'))
    benchmark_qqq_summary_id = Column(Integer, ForeignKey('equity_technical_summaries.id'))
    historical_earnings_count = Column(Integer, nullable=False, default=0)
    details_json = Column(JSONB)
    checked_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('current_event_id', name='uq_earnings_data_readiness_event'),
        Index('idx_earnings_data_readiness_ticker_report', ticker, report_date),
        Index('idx_earnings_data_readiness_status', status),
    )

class OptionChainSummary(Base):
    __tablename__ = 'option_chain_summaries'

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), nullable=False)
    window_id = Column(String(100), nullable=False)
    report_date = Column(Date, nullable=False)
    as_of_date = Column(Date, nullable=False)
    spot_price = Column(Numeric(20, 6))
    front_expiry = Column(Date)
    days_to_expiry = Column(Integer)
    atm_strike = Column(Numeric(20, 6))
    atm_call_mid = Column(Numeric(20, 6))
    atm_put_mid = Column(Numeric(20, 6))
    atm_straddle_mid = Column(Numeric(20, 6))
    implied_move_pct = Column(Numeric(20, 6))
    median_spread_pct = Column(Numeric(20, 6))
    atm_spread_pct = Column(Numeric(20, 6))
    total_call_volume = Column(Integer)
    total_put_volume = Column(Integer)
    call_put_volume_ratio = Column(Numeric(20, 6))
    liquidity_score = Column(Integer)
    volatility_pricing_score = Column(Integer)
    directional_skew_score = Column(Integer)
    summary_json = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('ticker', 'window_id', 'as_of_date', name='uq_option_chain_summary_scope'),
        Index('idx_option_chain_summary_ticker_report', ticker, report_date),
        Index('idx_option_chain_summary_as_of', as_of_date.desc()),
    )

class EarningsStrategyRun(Base):
    __tablename__ = 'earnings_strategy_runs'

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), nullable=False)
    report_date = Column(Date, nullable=False)
    provider = Column(String(100), nullable=False)
    model = Column(String(200))
    account = Column(String(100))
    status = Column(String(40), nullable=False, default='generated')
    input_json = Column(JSONB)
    strategy_json = Column(JSONB, nullable=False)
    warnings_json = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_earnings_strategy_runs_ticker_report', ticker, report_date),
        Index('idx_earnings_strategy_runs_provider', provider),
    )

class PaperOptionOrderDraft(Base):
    __tablename__ = 'paper_option_order_drafts'

    id = Column(Integer, primary_key=True)
    strategy_run_id = Column(Integer, ForeignKey('earnings_strategy_runs.id'), nullable=False)
    ticker = Column(String(20), nullable=False)
    report_date = Column(Date, nullable=False)
    strategy_index = Column(Integer, nullable=False)
    strategy_name = Column(String(300))
    scenario = Column(String(100))
    leg_index = Column(Integer, nullable=False)
    action = Column(String(20), nullable=False)
    option_type = Column(String(20), nullable=False)
    expiry = Column(Date, nullable=False)
    strike = Column(Numeric(20, 6), nullable=False)
    quantity = Column(Integer, nullable=False)
    limit_price_hint = Column(Numeric(20, 6))
    estimated_entry_price = Column(Numeric(20, 6))
    max_budget_to_use = Column(Numeric(20, 6))
    occ_symbol = Column(String(80), nullable=False)
    moomoo_code_candidate = Column(String(120))
    broker_code = Column(String(120))
    validation_status = Column(String(40), nullable=False, default='draft')
    validation_messages = Column(JSONB)
    raw_leg = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_paper_option_order_drafts_run', strategy_run_id),
        Index('idx_paper_option_order_drafts_ticker_report', ticker, report_date),
        Index('idx_paper_option_order_drafts_status', validation_status),
    )

class PaperOptionQuoteSnapshot(Base):
    __tablename__ = 'paper_option_quote_snapshots'

    id = Column(Integer, primary_key=True)
    order_draft_id = Column(Integer, ForeignKey('paper_option_order_drafts.id'), nullable=False)
    strategy_run_id = Column(Integer, ForeignKey('earnings_strategy_runs.id'), nullable=False)
    ticker = Column(String(20), nullable=False)
    occ_symbol = Column(String(80), nullable=False)
    broker_code = Column(String(120), nullable=False)
    quote_time = Column(DateTime(timezone=True))
    last_price = Column(Numeric(20, 6))
    bid_price = Column(Numeric(20, 6))
    ask_price = Column(Numeric(20, 6))
    mid_price = Column(Numeric(20, 6))
    bid_vol = Column(Numeric(20, 6))
    ask_vol = Column(Numeric(20, 6))
    volume = Column(Numeric(20, 6))
    open_interest = Column(Numeric(20, 6))
    implied_volatility = Column(Numeric(20, 6))
    delta = Column(Numeric(20, 6))
    gamma = Column(Numeric(20, 6))
    theta = Column(Numeric(20, 6))
    vega = Column(Numeric(20, 6))
    rho = Column(Numeric(20, 6))
    status = Column(String(40), nullable=False, default='ok')
    raw_snapshot = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_paper_option_quote_snapshots_draft', order_draft_id),
        Index('idx_paper_option_quote_snapshots_run', strategy_run_id),
        Index('idx_paper_option_quote_snapshots_code', broker_code),
    )

class PaperOptionExecutionPlan(Base):
    __tablename__ = 'paper_option_execution_plans'

    id = Column(Integer, primary_key=True)
    strategy_run_id = Column(Integer, ForeignKey('earnings_strategy_runs.id'), nullable=False)
    ticker = Column(String(20), nullable=False)
    report_date = Column(Date, nullable=False)
    strategy_index = Column(Integer, nullable=False)
    strategy_name = Column(String(300))
    scenario = Column(String(100))
    status = Column(String(40), nullable=False, default='needs_review')
    estimated_mid_debit = Column(Numeric(20, 6))
    conservative_net_debit = Column(Numeric(20, 6))
    estimated_max_loss = Column(Numeric(20, 6))
    max_budget_to_use = Column(Numeric(20, 6))
    budget_ok = Column(Boolean, nullable=False, default=False)
    liquidity_ok = Column(Boolean, nullable=False, default=False)
    quote_fresh_ok = Column(Boolean, nullable=False, default=False)
    structure_ok = Column(Boolean, nullable=False, default=False)
    max_spread_pct = Column(Numeric(20, 6))
    max_quote_age_minutes = Column(Numeric(20, 6))
    legs_json = Column(JSONB)
    checks_json = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_paper_option_execution_plans_run', strategy_run_id),
        Index('idx_paper_option_execution_plans_ticker_report', ticker, report_date),
        Index('idx_paper_option_execution_plans_status', status),
    )

class PaperOptionAdjustmentSuggestion(Base):
    __tablename__ = 'paper_option_adjustment_suggestions'

    id = Column(Integer, primary_key=True)
    execution_plan_id = Column(Integer, ForeignKey('paper_option_execution_plans.id'), nullable=False)
    strategy_run_id = Column(Integer, ForeignKey('earnings_strategy_runs.id'), nullable=False)
    ticker = Column(String(20), nullable=False)
    report_date = Column(Date, nullable=False)
    strategy_index = Column(Integer, nullable=False)
    strategy_name = Column(String(300))
    status = Column(String(40), nullable=False, default='needs_review')
    recommendation = Column(String(80), nullable=False)
    original_quantity = Column(Integer)
    suggested_quantity = Column(Integer)
    original_conservative_debit = Column(Numeric(20, 6))
    suggested_conservative_debit = Column(Numeric(20, 6))
    budget_limit = Column(Numeric(20, 6))
    max_spread_pct = Column(Numeric(20, 6))
    reason_json = Column(JSONB)
    suggested_legs_json = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_paper_option_adjustments_plan', execution_plan_id),
        Index('idx_paper_option_adjustments_run', strategy_run_id),
        Index('idx_paper_option_adjustments_status', status),
    )

class PaperOptionManualApproval(Base):
    __tablename__ = 'paper_option_manual_approvals'

    id = Column(Integer, primary_key=True)
    adjustment_suggestion_id = Column(Integer, ForeignKey('paper_option_adjustment_suggestions.id'), nullable=False)
    strategy_run_id = Column(Integer, ForeignKey('earnings_strategy_runs.id'), nullable=False)
    ticker = Column(String(20), nullable=False)
    report_date = Column(Date, nullable=False)
    strategy_index = Column(Integer, nullable=False)
    strategy_name = Column(String(300))
    status = Column(String(40), nullable=False, default='pending')
    telegram_chat_id = Column(String(80))
    telegram_message_id = Column(String(80))
    requested_payload = Column(JSONB)
    decided_at = Column(DateTime(timezone=True))
    decision_payload = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_paper_option_manual_approvals_suggestion', adjustment_suggestion_id),
        Index('idx_paper_option_manual_approvals_run', strategy_run_id),
        Index('idx_paper_option_manual_approvals_status', status),
    )

class PaperOptionOrderBatch(Base):
    __tablename__ = 'paper_option_order_batches'

    id = Column(Integer, primary_key=True)
    manual_approval_id = Column(Integer, ForeignKey('paper_option_manual_approvals.id'), nullable=False)
    adjustment_suggestion_id = Column(Integer, ForeignKey('paper_option_adjustment_suggestions.id'), nullable=False)
    strategy_run_id = Column(Integer, ForeignKey('earnings_strategy_runs.id'), nullable=False)
    ticker = Column(String(20), nullable=False)
    report_date = Column(Date, nullable=False)
    strategy_index = Column(Integer, nullable=False)
    strategy_name = Column(String(300))
    status = Column(String(40), nullable=False, default='staged')
    estimated_cost = Column(Numeric(20, 6))
    payload_json = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    submitted_at = Column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint('manual_approval_id', name='uq_paper_option_order_batch_approval'),
        Index('idx_paper_option_order_batches_run', strategy_run_id),
        Index('idx_paper_option_order_batches_status', status),
    )

class PaperOptionOrderBatchLeg(Base):
    __tablename__ = 'paper_option_order_batch_legs'

    id = Column(Integer, primary_key=True)
    order_batch_id = Column(Integer, ForeignKey('paper_option_order_batches.id'), nullable=False)
    draft_id = Column(Integer, ForeignKey('paper_option_order_drafts.id'))
    leg_index = Column(Integer, nullable=False)
    action = Column(String(20), nullable=False)
    option_type = Column(String(20), nullable=False)
    expiry = Column(Date, nullable=False)
    strike = Column(Numeric(20, 6), nullable=False)
    quantity = Column(Integer, nullable=False)
    broker_code = Column(String(120), nullable=False)
    occ_symbol = Column(String(80))
    suggested_limit_price = Column(Numeric(20, 6))
    order_type = Column(String(40), nullable=False, default='limit')
    status = Column(String(40), nullable=False, default='staged')
    broker_order_id = Column(String(120))
    dealt_qty = Column(Numeric(20, 6))
    dealt_avg_price = Column(Numeric(20, 6))
    last_err_msg = Column(Text)
    last_status_at = Column(DateTime(timezone=True))
    payload_json = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_paper_option_order_batch_legs_batch', order_batch_id),
        Index('idx_paper_option_order_batch_legs_status', status),
    )

class PaperOptionPositionSnapshot(Base):
    __tablename__ = 'paper_option_position_snapshots'

    id = Column(Integer, primary_key=True)
    order_batch_id = Column(Integer, ForeignKey('paper_option_order_batches.id'), nullable=False)
    strategy_run_id = Column(Integer, ForeignKey('earnings_strategy_runs.id'), nullable=False)
    ticker = Column(String(20), nullable=False)
    status = Column(String(40), nullable=False, default='open')
    entry_net_debit = Column(Numeric(20, 6))
    current_exit_value = Column(Numeric(20, 6))
    unrealized_pl = Column(Numeric(20, 6))
    unrealized_pl_pct = Column(Numeric(20, 6))
    max_profit = Column(Numeric(20, 6))
    max_loss = Column(Numeric(20, 6))
    quote_json = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_paper_option_position_snapshots_batch', order_batch_id),
        Index('idx_paper_option_position_snapshots_status', status),
    )

class PaperOptionExitPlan(Base):
    __tablename__ = 'paper_option_exit_plans'

    id = Column(Integer, primary_key=True)
    position_snapshot_id = Column(Integer, ForeignKey('paper_option_position_snapshots.id'), nullable=False)
    order_batch_id = Column(Integer, ForeignKey('paper_option_order_batches.id'), nullable=False)
    strategy_run_id = Column(Integer, ForeignKey('earnings_strategy_runs.id'), nullable=False)
    ticker = Column(String(20), nullable=False)
    action = Column(String(80), nullable=False)
    status = Column(String(40), nullable=False, default='monitor')
    reason_json = Column(JSONB)
    exit_legs_json = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_paper_option_exit_plans_batch', order_batch_id),
        Index('idx_paper_option_exit_plans_status', status),
    )

class PaperOptionExitApproval(Base):
    __tablename__ = 'paper_option_exit_approvals'

    id = Column(Integer, primary_key=True)
    exit_plan_id = Column(Integer, ForeignKey('paper_option_exit_plans.id'), nullable=False)
    order_batch_id = Column(Integer, ForeignKey('paper_option_order_batches.id'), nullable=False)
    strategy_run_id = Column(Integer, ForeignKey('earnings_strategy_runs.id'), nullable=False)
    ticker = Column(String(20), nullable=False)
    action = Column(String(80), nullable=False)
    status = Column(String(40), nullable=False, default='pending')
    telegram_chat_id = Column(String(80))
    telegram_message_id = Column(String(80))
    requested_payload = Column(JSONB)
    decided_at = Column(DateTime(timezone=True))
    decision_payload = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_paper_option_exit_approvals_plan', exit_plan_id),
        Index('idx_paper_option_exit_approvals_batch', order_batch_id),
        Index('idx_paper_option_exit_approvals_status', status),
    )

class PaperOptionExitOrderBatch(Base):
    __tablename__ = 'paper_option_exit_order_batches'

    id = Column(Integer, primary_key=True)
    exit_approval_id = Column(Integer, ForeignKey('paper_option_exit_approvals.id'), nullable=False)
    exit_plan_id = Column(Integer, ForeignKey('paper_option_exit_plans.id'), nullable=False)
    source_order_batch_id = Column(Integer, ForeignKey('paper_option_order_batches.id'), nullable=False)
    strategy_run_id = Column(Integer, ForeignKey('earnings_strategy_runs.id'), nullable=False)
    ticker = Column(String(20), nullable=False)
    status = Column(String(40), nullable=False, default='staged')
    payload_json = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    submitted_at = Column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint('exit_approval_id', name='uq_paper_option_exit_order_batch_approval'),
        Index('idx_paper_option_exit_order_batches_source', source_order_batch_id),
        Index('idx_paper_option_exit_order_batches_status', status),
    )

class PaperOptionExitOrderBatchLeg(Base):
    __tablename__ = 'paper_option_exit_order_batch_legs'

    id = Column(Integer, primary_key=True)
    exit_order_batch_id = Column(Integer, ForeignKey('paper_option_exit_order_batches.id'), nullable=False)
    source_batch_leg_id = Column(Integer, ForeignKey('paper_option_order_batch_legs.id'), nullable=False)
    leg_index = Column(Integer, nullable=False)
    action = Column(String(20), nullable=False)
    quantity = Column(Integer, nullable=False)
    broker_code = Column(String(120), nullable=False)
    suggested_limit_price = Column(Numeric(20, 6))
    order_type = Column(String(40), nullable=False, default='limit')
    status = Column(String(40), nullable=False, default='staged')
    broker_order_id = Column(String(120))
    payload_json = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_paper_option_exit_order_batch_legs_batch', exit_order_batch_id),
        Index('idx_paper_option_exit_order_batch_legs_status', status),
    )

engine = create_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)
    print("✅ 数据库表已初始化。")

if __name__ == "__main__":
    init_db()
