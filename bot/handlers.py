import logging
import asyncio
from datetime import datetime
from telethon import TelegramClient, events
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pytz import timezone
from utils.config import config
from scraper.fintel import FintelScraper

logger = logging.getLogger(__name__)

class ShortBot:
    def __init__(self):
        # 使用 Bot Token 模式初始化 Client
        self.client = TelegramClient(config.SESSION_NAME, config.API_ID, config.API_HASH)
        self.scraper = FintelScraper(visible=False)
        self.scheduler = AsyncIOScheduler()
        self.tz = timezone('US/Central')

    def format_message(self, df, is_scheduled=False):
        if df is None or df.empty:
            return "❌ 抓取失败，请检查账号状态或稍后再试。"
        
        prefix = "📢 **[定时推送]** " if is_scheduled else "🔥 "
        msg = f"{prefix}**Fintel 做空挤压榜 Top 30**\n"
        msg += f"📅 {datetime.now(self.tz).strftime('%Y-%m-%d %H:%M')} CT\n\n"
        
        # 表头
        msg += "`顺序 | 股票   | 评分  | 费率` \n"
        msg += "───|──────|──────|─────\n"
        
        for _, row in df.iterrows():
            rank = str(row.get('Rank', '?')).ljust(2)
            full_security = str(row.get('Security', 'Unknown'))
            ticker = full_security.split(' / ')[0].strip().upper()
            
            score = str(row.get('Short Squeeze Score', 'N/A')).ljust(5)
            fee = str(row.get('Borrow Fee Rate', 'N/A'))
            
            yahoo_link = f"https://finance.yahoo.com/quote/{ticker}"
            
            # 使用 MarkdownV2 的等宽字体组合链接（注意：Telegram 部分客户端在 code 块内不支持链接，
            # 所以我们用等宽字符模拟对齐，链接单独处理）
            msg += f"`{rank} | `[{ticker.ljust(6)}]({yahoo_link})` | {score} | {fee}%` \n"
            
        msg += "\n💡 点击代码查看雅虎财经详情"
        return msg

    async def send_scheduled_report(self):
        """定时任务：执行抓取并发送至目标群组"""
        logger.info("开始执行定时抓取任务...")
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(None, self.scraper.run)
        
        if df is not None:
            message = self.format_message(df, is_scheduled=True)
            if config.TARGET_GROUP_ID != 0:
                # Bot 模式下发送消息
                await self.client.send_message(config.TARGET_GROUP_ID, message)
                logger.info(f"定时报告已由 Bot 发送至群组: {config.TARGET_GROUP_ID}")
            else:
                logger.warning("未配置 TARGET_GROUP_ID，定时报告发送失败。")
        else:
            logger.error("定时抓取失败，未发送报告。")

    async def start(self):
        # 核心改动：使用 bot_token 登录
        logger.info("正在以 Bot 模式启动...")
        await self.client.start(bot_token=config.TELEGRAM_BOT_TOKEN)
        logger.info("🤖 ShortChunwuBot 已在线")

        # 配置定时任务
        self.scheduler.add_job(self.send_scheduled_report, 'cron', hour=8, minute=15, timezone=self.tz)
        self.scheduler.add_job(self.send_scheduled_report, 'cron', hour=15, minute=15, timezone=self.tz)
        self.scheduler.start()
        logger.info("⏰ 定时推送已就绪 (8:15 AM & 3:15 PM CT)")

        # 1. 监听手动排行榜指令
        @self.client.on(events.NewMessage(pattern=r'(?i)/top'))
        async def handle_top(event):
            logger.info(f"Bot 收到 /top 指令 - 来自: {event.chat_id}")
            await event.respond("⏳ 正在实时抓取 Fintel 数据，请稍候...")
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(None, self.scraper.run)
            message = self.format_message(df)
            await event.respond(message)

        # 2. 监听测试指令
        @self.client.on(events.NewMessage(pattern=r'(?i)/test_push'))
        async def handle_test(event):
            await event.respond("🤖 Bot 正在测试推送逻辑...")
            await self.send_scheduled_report()

        # 3. 监听开始指令
        @self.client.on(events.NewMessage(pattern=r'(?i)/start'))
        async def handle_start(event):
            await event.respond("你好！我是 ShortChunwuBot。\n"
                                "✅ 我会每天 8:15 & 15:15 CT 自动发送做空榜单。\n"
                                "✅ 你也可以随时输入 `/top` 让我即时抓取。")

        await self.client.run_until_disconnected()
