import time
import logging
import pandas as pd
import hashlib
import numpy as np
import html
import requests
from datetime import datetime
from pytz import timezone
from scraper.fintel import FintelScraper
from utils.config import config
from utils.db import SessionLocal, ShortSqueeze, GammaSqueeze, FintelSout, OptionFlow
from sqlalchemy.exc import IntegrityError

# 配置独立日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - ScraperService - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

CT_TZ = timezone('US/Central')
SOUT_ALERT_WINDOWS_CT = (
    (8 * 60 + 30, 9 * 60),       # 08:30-09:00 CT, 开盘后 30 分钟
    (14 * 60 + 30, 15 * 60),     # 14:30-15:00 CT, 收盘前 30 分钟
)
SOUT_ALERT_MAX_DTX = 60
SOUT_ALERT_MIN_SIGMA = 2
SOUT_ALERT_CONTRACTS = ('CALL', 'PUT')

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

def is_sout_alert_window():
    """开盘后 30 分钟和收盘前 30 分钟，按 CT 计算。"""
    now = datetime.now(CT_TZ)
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return any(start <= minutes <= end for start, end in SOUT_ALERT_WINDOWS_CT)

def convert_et_to_ct(time_str):
    try:
        et_time = datetime.strptime(str(time_str)[:5], "%H:%M")
        ct_time = et_time - pd.Timedelta(hours=1)
        return ct_time.strftime("%H:%M")
    except Exception:
        return str(time_str)[:5]

def is_sout_alert_match(row_dict):
    if str(row_dict.get('Trade Side', '')).upper() != 'BUY':
        return False
    if str(row_dict.get('Contract', '')).upper() not in SOUT_ALERT_CONTRACTS:
        return False
    try:
        dtx_val = int(pd.to_numeric(row_dict.get('DTX', 999), errors='coerce'))
        sigma_val = float(pd.to_numeric(row_dict.get('Premium Sigmas', 0), errors='coerce'))
    except Exception:
        return False
    return dtx_val <= SOUT_ALERT_MAX_DTX and sigma_val > SOUT_ALERT_MIN_SIGMA

def format_sout_alert_line(row_dict):
    security = str(row_dict.get('Security', ''))
    ticker = security.split(' / ')[0].strip().upper()
    if not ticker or ticker == 'UNKNOWN' or ' / ' not in security:
        ticker = str(row_dict.get('Symbol', row_dict.get('Ticker', 'N/A'))).strip().upper().split(':')[0]

    contract = html.escape(str(row_dict.get('Contract', '')).upper())
    t_ct = html.escape(convert_et_to_ct(row_dict.get('Time', '--:--')))
    dtx = html.escape(str(row_dict.get('DTX', '0')))
    sigma = float(pd.to_numeric(row_dict.get('Premium Sigmas', 0), errors='coerce'))
    premium = pd.to_numeric(row_dict.get('Premium Paid ($)', 0), errors='coerce')
    if pd.isna(premium):
        premium = 0
    if abs(premium) >= 1000000:
        premium_text = f"{premium/1000000:.1f}M"
    elif abs(premium) >= 1000:
        premium_text = f"{premium/1000:.0f}K"
    else:
        premium_text = f"{premium:.0f}"

    strike_val = row_dict.get('Strike Price')
    try:
        strike = f"${float(pd.to_numeric(strike_val, errors='coerce')):g}"
    except Exception:
        strike = f"${strike_val}" if strike_val else "N/A"

    ticker_safe = html.escape(ticker)
    link = f"https://www.google.com/finance/quote/{ticker_safe}:NASDAQ"
    return (
        f"<code>{t_ct}</code> <a href=\"{link}\">{ticker_safe}</a> "
        f"<code>{contract}</code> <code>{dtx}d</code> "
        f"<code>{html.escape(str(strike))}</code> <code>{premium_text}</code> "
        f"<code>s:{sigma:.1f}</code>"
    )

def send_sout_alerts(rows):
    if not rows or not config.TELEGRAM_BOT_TOKEN or not config.TARGET_GROUP_ID:
        return
    if not is_sout_alert_window():
        return

    matched = [row for row in rows if is_sout_alert_match(row)]
    if not matched:
        return

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    for i in range(0, len(matched), 20):
        chunk = matched[i:i + 20]
        message = (
            f"📢 <b>BUY CALL / BUY PUT 更新</b> ({datetime.now(CT_TZ).strftime('%H:%M')} CT)\n"
            "<code>DTX&lt;=60</code> <code>Sigma&gt;2</code>\n"
            + "\n".join(format_sout_alert_line(row) for row in chunk)
        )
        try:
            resp = requests.post(
                url,
                json={
                    "chat_id": config.TARGET_GROUP_ID,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                    "reply_markup": {"inline_keyboard": [[{"text": "📋 菜单", "callback_data": "menu"}]]},
                },
                timeout=10,
            )
            if resp.status_code >= 400:
                logger.error(f"SOUT 推送失败: {resp.status_code} {resp.text}")
            else:
                logger.info(f"📨 SOUT 提醒已推送 {len(chunk)} 条。")
        except Exception as e:
            logger.error(f"SOUT 推送异常: {e}")

def save_to_db(df, model_class):
    """通用持久化逻辑，支持增量去重"""
    if df is None or df.empty:
        return []

    # 预处理：将所有 NaN 替换为 None
    df = df.replace({np.nan: None})

    db = SessionLocal()
    try:
        scraped_at = datetime.now()
        count = 0
        inserted_sout_rows = []
        
        if model_class == FintelSout:
            for _, row in df.iterrows():
                row_dict = clean_dict(row.to_dict())
                ticker = str(row_dict.get('Symbol', 'Unknown')).strip().upper()
                current_hash = get_row_hash(row_dict)

                if db.query(FintelSout.id).filter(FintelSout.data_hash == current_hash).first():
                    continue
                
                try:
                    with db.begin_nested():
                        record = FintelSout(
                            scraped_at=scraped_at,
                            ticker=ticker,
                            security_name=str(row_dict.get('Security', ticker)),
                            metrics=row_dict,
                            data_hash=current_hash
                        )
                        db.add(record)
                    count += 1
                    inserted_sout_rows.append(row_dict)
                except IntegrityError:
                    continue
                except Exception as row_e:
                    logger.error(f"处理单行 SOUT 失败: {row_e}")
                    continue
        else:
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
        return inserted_sout_rows if model_class == FintelSout else []
            
    except Exception as e:
        db.rollback()
        logger.error(f"❌ 数据库操作整体失败: {e}")
        return []
    finally:
        db.close()

def is_market_hours():
    """判断当前是否在交易时间内 (周一至周五 08:00 - 15:30 CT)"""
    now = datetime.now(CT_TZ)
    if now.weekday() >= 5: return False
    start_time = now.replace(hour=8, minute=0, second=0, microsecond=0)
    end_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return start_time <= now <= end_time

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
            if not is_market_hours():
                if tick % 60 == 0:
                    logger.info("非交易时段 (08:00-15:30 CT, Mon-Fri)，采集器静默休眠...")
                if scraper.driver:
                    scraper.stop_browser()
                time.sleep(60)
                tick += 1
                continue

            if not scraper.driver:
                scraper.start_browser(urls)
            
            # 高频抓取 (1 min)
            inserted_sout_rows = save_to_db(scraper.scrape_from_tab_no_refresh(urls[0]), FintelSout)
            send_sout_alerts(inserted_sout_rows)
            
            # 低频刷新 (30 mins)
            if tick % 30 == 0:
                logger.info(f"📅 [Tick {tick}] 执行低频全量更新...")
                save_to_db(scraper.scrape_from_tab(urls[1]), ShortSqueeze)
                save_to_db(scraper.scrape_from_tab(urls[2]), GammaSqueeze)
                save_to_db(scraper.scrape_from_tab(urls[3]), OptionFlow)
                logger.info("✅ 低频全量更新完成。")
            
            tick += 1
            if tick >= 600:
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
