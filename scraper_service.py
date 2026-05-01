import time
import logging
import pandas as pd
import hashlib
import json
import numpy as np
from datetime import datetime
from scraper.fintel import FintelScraper
from utils.db import SessionLocal, ShortSqueeze, GammaSqueeze, FintelSout, OptionFlow
from sqlalchemy import desc

# 配置独立日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - ScraperService - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_row_hash(row_dict):
    """计算行数据的 MD5 哈希用于去重"""
    # 移除可能变动的 rank 或 timestamp 相关字段，仅对核心业务数据求哈希
    core_data = {k: v for k, v in row_dict.items() if k not in ['Rank', 'scraped_at', 'Δ']}
    s = json.dumps(core_data, sort_keys=True)
    return hashlib.md5(s.encode('utf-8')).hexdigest()

def save_to_db(df, model_class):
    """通用持久化逻辑"""
    if df is None or df.empty:
        return

    # 预处理：将所有 NaN 替换为 None，确保 JSONB 序列化成功
    df = df.replace({np.nan: None})

    db = SessionLocal()
    try:
        scraped_at = datetime.now()
        records = []
        
        if model_class == FintelSout:
            for _, row in df.iterrows():
                row_dict = row.to_dict()
                row_dict = {k: (None if pd.isna(v) else v) for k, v in row_dict.items()}
                ticker = str(row.get('Security', 'Unknown')).split(' / ')[0].strip().upper()
                current_hash = get_row_hash(row_dict)
                last_record = db.query(FintelSout).filter(FintelSout.ticker == ticker).order_by(desc(FintelSout.scraped_at)).first()
                if last_record and last_record.data_hash == current_hash:
                    continue
                records.append(FintelSout(
                    scraped_at=scraped_at, ticker=ticker, security_name=str(row.get('Security', 'Unknown')),
                    metrics=row_dict, data_hash=current_hash
                ))
        
        elif model_class == ShortSqueeze:
            for _, row in df.iterrows():
                si_change_col = [c for c in df.columns if 'SI Change' in str(c)][0]
                records.append(ShortSqueeze(
                    scraped_at=scraped_at, rank=int(row.get('Rank', 0)),
                    ticker=str(row.get('Security', 'Unknown')).split(' / ')[0].strip().upper(),
                    security_name=str(row.get('Security', 'Unknown')),
                    score=pd.to_numeric(row.get('Short Squeeze Score', 0), errors='coerce'),
                    borrow_fee_rate=pd.to_numeric(row.get('Borrow Fee Rate', 0), errors='coerce'),
                    short_float_pct=pd.to_numeric(row.get('Short Float', 0), errors='coerce'),
                    si_change_1m_pct=pd.to_numeric(row.get(si_change_col, 0), errors='coerce')
                ))
        
        elif model_class == GammaSqueeze:
            for _, row in df.iterrows():
                records.append(GammaSqueeze(
                    scraped_at=scraped_at, rank=int(row.get('Rank', 0)),
                    ticker=str(row.get('Security', 'Unknown')).split(' / ')[0].strip().upper(),
                    security_name=str(row.get('Security', 'Unknown')),
                    score=pd.to_numeric(row.get('Gamma Squeeze Score', 0), errors='coerce'),
                    gex_mm=pd.to_numeric(row.get('GEX ($MM)', 0), errors='coerce'),
                    put_call_ratio=pd.to_numeric(row.get('Put/Call Ratio', 0), errors='coerce'),
                    price_momo_1w_pct=pd.to_numeric(row.get('Price Momo (1w %)', 0), errors='coerce')
                ))

        elif model_class == OptionFlow:
            for _, row in df.iterrows():
                records.append(OptionFlow(
                    scraped_at=scraped_at, rank=int(row.get('Rank', 0)),
                    ticker=str(row.get('Security', 'Unknown')).split(' / ')[0].strip().upper(),
                    security_name=str(row.get('Security', 'Unknown')),
                    net_premium=pd.to_numeric(row.get('Net Premium', 0), errors='coerce'),
                    put_call_ratio=pd.to_numeric(row.get('Put/Call Ratio', 0), errors='coerce')
                ))

        if records:
            db.bulk_save_objects(records)
            db.commit()
            logger.info(f"✅ [{model_class.__tablename__}] 插入 {len(records)} 条新记录。")
            
    except Exception as e:
        db.rollback()
        logger.error(f"❌ 数据库操作失败: {e}")
    finally:
        db.close()

def main_loop():
    scraper = FintelScraper(visible=False)
    urls = [
        "https://fintel.io/sout",           # 0: Unusual Trades (1 min)
        "https://fintel.io/shortSqueeze",   # 1: Short (30 mins)
        "https://fintel.io/gammaSqueeze",   # 2: Gamma (30 mins)
        "https://fintel.io/sofStockLeaderboard" # 3: Option Flow (30 mins)
    ]
    
    tick = 0
    while True:
        try:
            if not scraper.driver:
                scraper.start_browser(urls)
            
            # --- 1. 高频任务 (每 1 分钟) ---
            logger.info(f"⏱ [Tick {tick}] 执行高频实时抓取: Unusual Trades (/sout)")
            sout_df = scraper.scrape_from_tab_no_refresh(urls[0])
            save_to_db(sout_df, FintelSout)
            
            # --- 2. 低频任务 (每 30 分钟) ---
            if tick % 30 == 0:
                logger.info(f"📅 [Tick {tick}] 执行低频全量更新: Short / Gamma / Option Flow")
                
                # 抓取并保存三个榜单
                save_to_db(scraper.scrape_from_tab(urls[1]), ShortSqueeze)
                save_to_db(scraper.scrape_from_tab(urls[2]), GammaSqueeze)
                save_to_db(scraper.scrape_from_tab(urls[3]), OptionFlow)
                
                logger.info("✅ 低频全量更新完成。")
            
            tick += 1
            if tick >= 600: # 约 10 小时重启一次浏览器释放内存
                logger.info("♻️ 周期性回收浏览器资源...")
                scraper.stop_browser()
                tick = 0
                
            time.sleep(60)
            
        except Exception as e:
            logger.error(f"主循环异常: {e}")
            scraper.stop_browser()
            time.sleep(60)

if __name__ == "__main__":
    main_loop()
