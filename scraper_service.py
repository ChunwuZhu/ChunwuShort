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
from sqlalchemy.exc import IntegrityError

# 配置独立日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - ScraperService - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_row_hash(row_dict):
    """根据日期、时间、Symbol和权利金计算唯一哈希（用户要求）"""
    keys = ['Date', 'Time', 'Symbol', 'Premium Paid ($)']
    core_values = []
    for k in keys:
        val = row_dict.get(k, '')
        if pd.isna(val): val = ''
        core_values.append(str(val))
    s = "|".join(core_values)
    return hashlib.md5(s.encode('utf-8')).hexdigest()

def clean_dict(d):
    """递归清理字典中的 NaN，替换为 None"""
    return {k: (None if pd.isna(v) else v) for k, v in d.items()}

def save_to_db(df, model_class):
    """通用持久化逻辑，支持增量去重"""
    if df is None or df.empty:
        return

    # 预处理：将所有 NaN 替换为 None
    df = df.replace({np.nan: None})

    db = SessionLocal()
    try:
        scraped_at = datetime.now()
        count = 0
        
        if model_class == FintelSout:
            # 1. 获取当前数据库中已有的所有哈希（为了效率，仅限当天的）
            # 或者简单点，我们直接利用 ON CONFLICT (已经在 DB 层级做了唯一约束)
            # 为了避免 rollback 导致 Session 丢失，我们使用 begin_nested()
            
            for _, row in df.iterrows():
                row_dict = clean_dict(row.to_dict())
                ticker = str(row_dict.get('Symbol', 'Unknown')).strip().upper()
                current_hash = get_row_hash(row_dict)
                
                try:
                    with db.begin_nested(): # 使用 Savepoint
                        record = FintelSout(
                            scraped_at=scraped_at,
                            ticker=ticker,
                            security_name=str(row_dict.get('Security', ticker)),
                            metrics=row_dict,
                            data_hash=current_hash
                        )
                        db.add(record)
                    count += 1
                except IntegrityError:
                    # 捕获唯一性冲突，不做处理，继续下一条
                    continue
                except Exception as row_e:
                    logger.error(f"处理单行 SOUT 失败: {row_e}")
                    continue
        else:
            # Short / Gamma / Option Flow 逻辑不变 (它们通常全量覆盖，不走唯一哈希)
            records = []
            for _, row in df.iterrows():
                if model_class == ShortSqueeze:
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
                    records.append(OptionFlow(
                        scraped_at=scraped_at, rank=int(row.get('Rank', 0)),
                        ticker=str(row.get('Security', 'Unknown')).split(' / ')[0].strip().upper(),
                        security_name=str(row.get('Security', 'Unknown')),
                        net_premium=pd.to_numeric(row.get('Net Premium', 0), errors='coerce'),
                        put_call_ratio=pd.to_numeric(row.get('Put/Call Ratio', 0), errors='coerce')
                    ))
            if records:
                db.bulk_save_objects(records)
                count = len(records)
        
        db.commit()
        if count > 0:
            logger.info(f"✅ [{model_class.__tablename__}] 成功存入 {count} 条记录。")
            
    except Exception as e:
        db.rollback()
        logger.error(f"❌ 数据库操作整体失败: {e}")
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
            
            # 每一分钟抓取一次
            save_to_db(scraper.scrape_from_tab_no_refresh(urls[0]), FintelSout)
            
            if tick % 30 == 0:
                save_to_db(scraper.scrape_from_tab(urls[1]), ShortSqueeze)
                save_to_db(scraper.scrape_from_tab(urls[2]), GammaSqueeze)
                save_to_db(scraper.scrape_from_tab(urls[3]), OptionFlow)
            
            tick += 1
            if tick >= 600:
                scraper.stop_browser()
                tick = 0
                
            time.sleep(60)
            
        except Exception as e:
            logger.error(f"主循环异常: {e}")
            scraper.stop_browser()
            time.sleep(60)

if __name__ == "__main__":
    main_loop()
