import logging
import asyncio
import pandas as pd
from datetime import datetime
from telethon import TelegramClient, events
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pytz import timezone
from utils.config import config
from scraper.fintel import FintelScraper

logger = logging.getLogger(__name__)

class ShortBot:
    def __init__(self):
        self.client = TelegramClient(config.SESSION_NAME, config.API_ID, config.API_HASH)
        self.scraper = FintelScraper(visible=False)
        self.scheduler = AsyncIOScheduler()
        self.tz = timezone('US/Central')

    def format_message(self, df, mode='top', is_scheduled=False):
        """
        mode='top': 按 Squeeze Score 排序 (Short)
        mode='change': 按 SI Change (1m %) 排序 (Short)
        mode='topg': 按 Gamma Squeeze Score 排序
        mode='changeg': 按 Gamma 相关变化排序 (如果 Fintel 页面有的话，默认按 Score)
        """
        if df is None or df.empty:
            return "❌ 抓取失败，请检查账号状态或稍后再试。"

        # 1. 识别列名 (Fintel 不同页面的列名可能微调)
        score_col = 'Short Squeeze Score' if 'Short Squeeze Score' in df.columns else 'Gamma Squeeze Score'
        float_col = 'Short Float' if 'Short Float' in df.columns else 'Net Institutional Flow' # Gamma 页可能没 Short Float
        
        # 寻找变化率列
        change_cols = [c for c in df.columns if 'Change' in c]
        change_col = change_cols[0] if change_cols else score_col

        # 转换数值
        for col in [score_col, float_col, change_col]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        # 2. 标题和排序逻辑
        if mode == 'top':
            title = "Fintel 做空挤压榜 Top 30"
            metric_label = "评分"
            df_sorted = df.sort_values(by=score_col, ascending=False).head(30)
            display_col = score_col
            unit = ""
        elif mode == 'change':
            title = "做空增幅榜 (SI Change) Top 30"
            metric_label = "变化"
            df_sorted = df.sort_values(by=change_col, ascending=False).head(30)
            display_col = change_col
            unit = "%"
        elif mode == 'topg':
            title = "Gamma Squeeze 榜 Top 30"
            metric_label = "评分"
            df_sorted = df.sort_values(by=score_col, ascending=False).head(30)
            display_col = score_col
            unit = ""
        elif mode == 'changeg':
            title = "Gamma 增幅榜 Top 30"
            metric_label = "变化"
            # 如果没有变化率列，按 Score 排
            df_sorted = df.sort_values(by=change_col, ascending=False).head(30)
            display_col = change_col
            unit = "%" if change_col != score_col else ""

        prefix = "📢 **[定时推送]** " if is_scheduled else "🔥 "
        msg = f"{prefix}**{title}**\n"
        msg += f"📅 {datetime.now(self.tz).strftime('%Y-%m-%d %H:%M')} CT\n\n"

        # 表头
        msg += f"`顺序 | 股票   | {metric_label.ljust(4)} | 做空  ` \n"
        msg += "`───|────────|──────|──────` \n"

        for i, (_, row) in enumerate(df_sorted.iterrows(), 1):
            rank = f"{i:02d}"
            full_security = str(row.get('Security', 'Unknown'))
            ticker = full_security.split(' / ')[0].strip().upper()
            
            val = f"{float(row.get(display_col, 0)):>5.1f}{unit}"
            
            # 做空占比处理
            s_float_val = row.get(float_col, 0)
            if isinstance(s_float_val, (int, float)):
                short_float = f"{float(s_float_val):>5.1f}%"
            else:
                short_float = "  N/A"
            
            google_link = f"https://www.google.com/finance/quote/{ticker}:NASDAQ"
            msg += f"`{rank} | `[{ticker.ljust(6)}]({google_link})` | {val.ljust(4)} | {short_float}` \n"
            
        msg += "\n💡 点击代码查看 Google Finance 详情"
        return msg

    async def send_scheduled_report(self):
        logger.info("开始执行定时抓取任务...")
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(None, self.scraper.run, "https://fintel.io/shortSqueeze")
        if df is not None:
            message = self.format_message(df, mode='top', is_scheduled=True)
            await self.client.send_message(config.TARGET_GROUP_ID, message)

    async def start(self):
        logger.info("正在以 Bot 模式启动...")
        await self.client.start(bot_token=config.TELEGRAM_BOT_TOKEN)
        logger.info("🤖 ShortChunwuBot 已在线")

        self.scheduler.add_job(self.send_scheduled_report, 'cron', hour=8, minute=15, timezone=self.tz)
        self.scheduler.add_job(self.send_scheduled_report, 'cron', hour=15, minute=15, timezone=self.tz)
        self.scheduler.start()

        @self.client.on(events.NewMessage(pattern=r'(?i)/top$'))
        async def handle_top(event):
            await event.respond("⏳ 正在拉取 Fintel 挤压榜单...")
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(None, self.scraper.run, "https://fintel.io/shortSqueeze")
            await event.respond(self.format_message(df, mode='top'))

        @self.client.on(events.NewMessage(pattern=r'(?i)/change$'))
        async def handle_change(event):
            await event.respond("⏳ 正在分析做空变化率榜单...")
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(None, self.scraper.run, "https://fintel.io/shortSqueeze")
            await event.respond(self.format_message(df, mode='change'))

        @self.client.on(events.NewMessage(pattern=r'(?i)/topg$'))
        async def handle_topg(event):
            await event.respond("⏳ 正在拉取 Fintel Gamma 挤压榜单...")
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(None, self.scraper.run, "https://fintel.io/gammaSqueeze")
            await event.respond(self.format_message(df, mode='topg'))

        @self.client.on(events.NewMessage(pattern=r'(?i)/changeg$'))
        async def handle_changeg(event):
            await event.respond("⏳ 正在分析 Gamma 增幅榜单...")
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(None, self.scraper.run, "https://fintel.io/gammaSqueeze")
            await event.respond(self.format_message(df, mode='changeg'))

        @self.client.on(events.NewMessage(pattern=r'(?i)/start'))
        async def handle_start(event):
            await event.respond("你好！我是 ShortChunwuBot。\n/top - 挤压榜单\n/change - 增幅榜单\n/topg - Gamma榜单\n/changeg - Gamma增幅\n?代码 - 快速获取谷歌财经链接 (如 ?TSLA)")

        # 4. 快速个股链接指令 (例如 ?TSLA)
        @self.client.on(events.NewMessage(pattern=r'^\?(\w+)'))
        async def handle_quick_link(event):
            ticker = event.pattern_match.group(1).upper()
            google_link = f"https://www.google.com/finance/quote/{ticker}:NASDAQ"
            message = f"🔍 **[{ticker}]({google_link})**"
            await event.respond(message, link_preview=False)

        await self.client.run_until_disconnected()
