import logging
import asyncio
import pandas as pd
from datetime import datetime
from telethon import TelegramClient, events
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pytz import timezone
from utils.config import config
from utils.db import SessionLocal, ShortSqueeze, GammaSqueeze
from sqlalchemy import func

logger = logging.getLogger(__name__)

class ShortBot:
    def __init__(self):
        self.client = TelegramClient(config.SESSION_NAME, config.API_ID, config.API_HASH)
        self.scheduler = AsyncIOScheduler()
        self.tz = timezone('US/Central')

    def get_latest_data(self, model_class):
        """从数据库获取最新的数据"""
        db = SessionLocal()
        try:
            # 找到最新的抓取时间戳
            latest_time = db.query(func.max(model_class.scraped_at)).scalar()
            if not latest_time:
                return None
            
            # 查询该时间戳下的所有记录
            results = db.query(model_class).filter(model_class.scraped_at == latest_time).order_by(model_class.rank.asc()).all()
            
            # 转换为 DataFrame
            data = []
            for r in results:
                if model_class == ShortSqueeze:
                    data.append({
                        'Rank': r.rank,
                        'Security': r.security_name,
                        'Short Squeeze Score': float(r.score or 0),
                        'Short Float': float(r.short_float_pct or 0),
                        'SI Change': float(r.si_change_1m_pct or 0),
                        'Borrow Fee Rate': float(r.borrow_fee_rate or 0)
                    })
                else: # GammaSqueeze
                    data.append({
                        'Rank': r.rank,
                        'Security': r.security_name,
                        'Gamma Squeeze Score': float(r.score or 0),
                        'GEX ($MM)': float(r.gex_mm or 0),
                        'Put/Call Ratio': float(r.put_call_ratio or 0),
                        'Price Momo (1w %)': float(r.price_momo_1w_pct or 0)
                    })
            return pd.DataFrame(data)
        finally:
            db.close()

    def format_message(self, df, mode='top', is_scheduled=False):
        if df is None or df.empty:
            return "❌ 数据库中暂无数据。请确保抓取服务已启动。"

        # 2. 标题和排序逻辑
        is_gamma = mode in ['topg', 'changeg']
        
        if mode == 'top':
            title, metric_label, display_col, unit = "Fintel 做空挤压榜 Top 30", "评分", "Short Squeeze Score", ""
            sec_label = "做空"
            sec_col = "Short Float"
        elif mode == 'change':
            title, metric_label, display_col, unit = "做空增幅榜 (SI Change) Top 30", "变化", "SI Change", "%"
            sec_label = "做空"
            sec_col = "Short Float"
        elif mode == 'topg':
            title, metric_label, display_col, unit = "Gamma Squeeze 榜 Top 30", "评分", "Gamma Squeeze Score", ""
            sec_label = "GEX/PCR"
        elif mode == 'changeg':
            title, metric_label, display_col, unit = "Gamma 增幅榜 Top 30", "变化", "Price Momo (1w %)", "%"
            sec_label = "GEX/PCR"

        # 重新排序
        df_sorted = df.sort_values(by=display_col, ascending=False).head(30)

        prefix = "📢 **[定时推送]** " if is_scheduled else "🔥 "
        msg = f"{prefix}**{title}**\n"
        msg += f"📅 {datetime.now(self.tz).strftime('%Y-%m-%d %H:%M')} CT\n\n"

        # 表头
        msg += f"`顺序 | 股票   | {metric_label.ljust(4)} | {sec_label.ljust(6)}` \n"
        msg += "`───|────────|──────|──────────` \n"

        for i, (_, row) in enumerate(df_sorted.iterrows(), 1):
            rank = f"{i:02d}"
            ticker = str(row.get('Security', 'Unknown')).split(' / ')[0].strip().upper()
            
            val_str = f"{float(row.get(display_col, 0)):>5.1f}{unit}"

            if is_gamma:
                gex = float(row.get('GEX ($MM)', 0))
                pcr = float(row.get('Put/Call Ratio', 0))
                sec_display = f"{gex:>3.0f}/{pcr:.1f}"
            else:
                s_float = float(row.get(sec_col, 0))
                sec_display = f"{s_float:>5.1f}%"
            
            google_link = f"https://www.google.com/finance/quote/{ticker}:NASDAQ"
            msg += f"`{rank} | `[{ticker.ljust(6)}]({google_link})` | {val_str.ljust(4)} | {sec_display}` \n"
            
        msg += "\n💡 点击代码查看 Google Finance 详情"
        return msg

    async def send_scheduled_report(self):
        logger.info("执行定时推送...")
        df = self.get_latest_data(ShortSqueeze)
        if df is not None:
            message = self.format_message(df, mode='top', is_scheduled=True)
            await self.client.send_message(config.TARGET_GROUP_ID, message)

    async def start(self):
        logger.info("正在以 Bot 模式启动...")
        await self.client.start(bot_token=config.TELEGRAM_BOT_TOKEN)
        logger.info("🤖 ShortChunwuBot 已在线 (数据库模式)")

        self.scheduler.add_job(self.send_scheduled_report, 'cron', hour=8, minute=15, timezone=self.tz)
        self.scheduler.add_job(self.send_scheduled_report, 'cron', hour=15, minute=15, timezone=self.tz)
        self.scheduler.start()

        @self.client.on(events.NewMessage(pattern=r'(?i)/top$'))
        async def handle_top(event):
            df = self.get_latest_data(ShortSqueeze)
            await event.respond(self.format_message(df, mode='top'))

        @self.client.on(events.NewMessage(pattern=r'(?i)/change$'))
        async def handle_change(event):
            df = self.get_latest_data(ShortSqueeze)
            await event.respond(self.format_message(df, mode='change'))

        @self.client.on(events.NewMessage(pattern=r'(?i)/topg$'))
        async def handle_topg(event):
            df = self.get_latest_data(GammaSqueeze)
            await event.respond(self.format_message(df, mode='topg'))

        @self.client.on(events.NewMessage(pattern=r'(?i)/changeg$'))
        async def handle_changeg(event):
            df = self.get_latest_data(GammaSqueeze)
            await event.respond(self.format_message(df, mode='changeg'))

        @self.client.on(events.NewMessage(pattern=r'(?i)/start$'))
        async def handle_start(event):
            await event.respond("欢迎使用 ShortChunwuBot！\n输入 `1` 查看所有可用指令。")

        @self.client.on(events.NewMessage(pattern=r'^1$'))
        async def handle_menu(event):
            menu_text = (
                "**ShortChunwuBot 🛠 菜单**\n"
                "───|────────|──────\n"
                "📊 **Short:**  /top | /change\n"
                "📈 **Gamma:** /topg | /changeg\n"
                "🔍 **Quick:** `?代码` (例: `?TSLA`)\n"
                "───|────────|──────\n"
                "⏰ 08:15 & 15:15 CT 自动推送"
            )
            await event.respond(menu_text)

        @self.client.on(events.NewMessage(pattern=r'^\?(\w+)'))
        async def handle_quick_link(event):
            ticker = event.pattern_match.group(1).upper()
            google_link = f"https://www.google.com/finance/quote/{ticker}:NASDAQ"
            message = f"🔍 **[{ticker}]({google_link})**"
            await event.respond(message, link_preview=False)

        await self.client.run_until_disconnected()
