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
        mode='top': 按 Squeeze Score 排序
        mode='change': 按 SI Change (1m %) 排序
        """
        if df is None or df.empty:
            return "❌ 抓取失败，请检查账号状态或稍后再试。"

        # 1. 数据预处理
        # 确保数值列正确转换
        score_col = 'Short Squeeze Score'
        fee_col = 'Borrow Fee Rate'
        # 处理带有特殊字符的列名
        change_col = [c for c in df.columns if 'SI Change' in c][0]

        df[score_col] = pd.to_numeric(df[score_col], errors='coerce').fillna(0)
        df[fee_col] = pd.to_numeric(df[fee_col], errors='coerce').fillna(0)
        df[change_col] = pd.to_numeric(df[change_col], errors='coerce').fillna(0)

        # 2. 排序逻辑
        if mode == 'top':
            title = "Fintel 做空挤压榜 Top 30"
            metric_label = "评分"
            # 默认就是按 Score 排序，确保万一重新排一次
            df_sorted = df.sort_values(by=score_col, ascending=False).head(30)
            display_col = score_col
            unit = ""
        else:
            title = "做空增幅榜 (SI Change) Top 30"
            metric_label = "变化"
            # 按变化率倒序
            df_sorted = df.sort_values(by=change_col, ascending=False).head(30)
            display_col = change_col
            unit = "%"

        prefix = "📢 **[定时推送]** " if is_scheduled else "🔥 "
        msg = f"{prefix}**{title}**\n"
        msg += f"📅 {datetime.now(self.tz).strftime('%Y-%m-%d %H:%M')} CT\n\n"

        # 表头
        msg += f"`顺序 | 股票   | {metric_label.ljust(4)} | 费率  `\n"
        msg += "`───|────────|──────|──────`\n"

        for i, (_, row) in enumerate(df_sorted.iterrows(), 1):
            rank = f"{i:02d}"
            full_security = str(row.get('Security', 'Unknown'))
            ticker = full_security.split(' / ')[0].strip().upper()
            
            val = f"{float(row[display_col]):>5.1f}{unit}"
            fee = f"{float(row[fee_col]):>5.1f}%"
            
            # TradingView 链接
            tv_link = f"https://www.tradingview.com/chart/?symbol={ticker}"
            
            msg += f"`{rank} | `[{ticker.ljust(6)}]({tv_link})` | {val.ljust(4)} | {fee}`\n"
            
        msg += "\n💡 点击代码查看 TradingView K线"
        return msg

    async def send_scheduled_report(self):
        logger.info("开始执行定时抓取任务...")
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(None, self.scraper.run)
        
        if df is not None:
            # 定时推送默认发 /top 榜单
            message = self.format_message(df, mode='top', is_scheduled=True)
            await self.client.send_message(config.TARGET_GROUP_ID, message)
        else:
            logger.error("定时抓取失败")

    async def start(self):
        logger.info("正在以 Bot 模式启动...")
        await self.client.start(bot_token=config.TELEGRAM_BOT_TOKEN)
        logger.info("🤖 ShortChunwuBot 已在线")

        self.scheduler.add_job(self.send_scheduled_report, 'cron', hour=8, minute=15, timezone=self.tz)
        self.scheduler.add_job(self.send_scheduled_report, 'cron', hour=15, minute=15, timezone=self.tz)
        self.scheduler.start()

        @self.client.on(events.NewMessage(pattern=r'(?i)/top'))
        async def handle_top(event):
            await event.respond("⏳ 正在拉取 Fintel 挤压榜单...")
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(None, self.scraper.run)
            await event.respond(self.format_message(df, mode='top'))

        @self.client.on(events.NewMessage(pattern=r'(?i)/change'))
        async def handle_change(event):
            await event.respond("⏳ 正在分析做空变化率榜单...")
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(None, self.scraper.run)
            await event.respond(self.format_message(df, mode='change'))

        @self.client.on(events.NewMessage(pattern=r'(?i)/test_push'))
        async def handle_test(event):
            await self.send_scheduled_report()

        @self.client.on(events.NewMessage(pattern=r'(?i)/start'))
        async def handle_start(event):
            await event.respond("你好！我是 ShortChunwuBot。\n/top - 挤压榜单\n/change - 增幅榜单")

        await self.client.run_until_disconnected()
