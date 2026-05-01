import time
import logging
import pandas as pd
from datetime import datetime
from scraper.fintel import FintelScraper
from utils.db import SessionLocal, ShortSqueeze, GammaSqueeze
from sqlalchemy import func

# 配置独立日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - ScraperService - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def save_to_db(df, model_class):
    """将 DataFrame 数据持久化到 PostgreSQL"""
    if df is None or df.empty:
        return

    db = SessionLocal()
    try:
        scraped_at = datetime.now()
        records = []
        
        for _, row in df.iterrows():
            if model_class == ShortSqueeze:
                # 寻找 SI Change 列 (列名中可能含有特殊字符)
                si_change_col = [c for c in df.columns if 'SI Change' in str(c)][0]
                
                record = ShortSqueeze(
                    scraped_at=scraped_at,
                    rank=int(row.get('Rank', 0)),
                    ticker=str(row.get('Security', 'Unknown')).split(' / ')[0].strip().upper(),
                    security_name=str(row.get('Security', 'Unknown')),
                    score=pd.to_numeric(row.get('Short Squeeze Score', 0), errors='coerce'),
                    borrow_fee_rate=pd.to_numeric(row.get('Borrow Fee Rate', 0), errors='coerce'),
                    short_float_pct=pd.to_numeric(row.get('Short Float', 0), errors='coerce'),
                    si_change_1m_pct=pd.to_numeric(row.get(si_change_col, 0), errors='coerce')
                )
            else: # GammaSqueeze
                record = GammaSqueeze(
                    scraped_at=scraped_at,
                    rank=int(row.get('Rank', 0)),
                    ticker=str(row.get('Security', 'Unknown')).split(' / ')[0].strip().upper(),
                    security_name=str(row.get('Security', 'Unknown')),
                    score=pd.to_numeric(row.get('Gamma Squeeze Score', 0), errors='coerce'),
                    gex_mm=pd.to_numeric(row.get('GEX ($MM)', 0), errors='coerce'),
                    put_call_ratio=pd.to_numeric(row.get('Put/Call Ratio', 0), errors='coerce'),
                    price_momo_1w_pct=pd.to_numeric(row.get('Price Momo (1w %)', 0), errors='coerce')
                )
            records.append(record)
        
        db.bulk_save_objects(records)
        db.commit()
        logger.info(f"✅ 成功向 {model_class.__tablename__} 插入 {len(records)} 条数据。")
    except Exception as e:
        db.rollback()
        logger.error(f"❌ 数据库写入失败: {e}")
    finally:
        db.close()

def main_loop():
    scraper = FintelScraper(visible=False)
    
    # 周期性重启浏览器，防止内存泄漏 (每 10 次循环重置一次)
    loop_count = 0
    
    while True:
        try:
            logger.info("--- 开始新一轮抓取周期 ---")
            
            # 1. 抓取 Short Squeeze
            short_df = scraper.scrape_url("https://fintel.io/shortSqueeze")
            save_to_db(short_df, ShortSqueeze)
            
            # 2. 抓取 Gamma Squeeze
            gamma_df = scraper.scrape_url("https://fintel.io/gammaSqueeze")
            save_to_db(gamma_df, GammaSqueeze)
            
            loop_count += 1
            if loop_count >= 10:
                logger.info("正在回收浏览器资源...")
                scraper.stop_browser()
                loop_count = 0
                
            logger.info("周期完成。等待 30 分钟...")
            time.sleep(30 * 60) # 30 分钟
            
        except Exception as e:
            logger.error(f"主循环异常: {e}")
            scraper.stop_browser() # 发生异常时关闭浏览器，下次循环重试
            time.sleep(60) # 报错后等 1 分钟再试

if __name__ == "__main__":
    main_loop()
