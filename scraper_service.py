import time
import logging
import pandas as pd
from datetime import datetime
from scraper.fintel import FintelScraper
from utils.db import SessionLocal, ShortSqueeze, GammaSqueeze

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
    urls = [
        "https://fintel.io/shortSqueeze",
        "https://fintel.io/gammaSqueeze"
    ]
    
    loop_count = 0
    
    while True:
        try:
            logger.info("--- 开始新一轮抓取周期 (多标签模式) ---")
            
            # 确保浏览器和标签页已初始化
            if not scraper.driver:
                scraper.start_browser(urls)
            
            # 1. 抓取 Short Squeeze (从对应标签页)
            short_df = scraper.scrape_from_tab(urls[0])
            save_to_db(short_df, ShortSqueeze)
            
            # 2. 抓取 Gamma Squeeze (从对应标签页)
            gamma_df = scraper.scrape_from_tab(urls[1])
            save_to_db(gamma_df, GammaSqueeze)
            
            loop_count += 1
            # 依然保留定期重启逻辑，增强稳定性
            if loop_count >= 20:
                logger.info("正在回收浏览器资源...")
                scraper.stop_browser()
                loop_count = 0
                
            logger.info("周期完成。等待 30 分钟...")
            time.sleep(30 * 60)
            
        except Exception as e:
            logger.error(f"主循环异常: {e}")
            scraper.stop_browser()
            time.sleep(60)

if __name__ == "__main__":
    main_loop()
