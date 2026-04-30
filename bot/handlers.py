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
        mode='changeg': 按 Gamma 变化排序
        mode='topo': 按 Net Premium 排序 (Option Flow)
        mode='changeo': 按 Option Flow 变化排序
        """
        if df is None or df.empty:
            return "❌ 抓取失败，请检查账号状态或稍后再试。"

        # 1. 识别核心列名
        score_col = None
        for c in ['Short Squeeze Score', 'Gamma Squeeze Score', 'Net Premium', 'NetPremium']:
            if c in df.columns:
                score_col = c
                break
        if not score_col: score_col = df.columns[2]

        # 寻找变化率列
        change_cols = [c for c in df.columns if 'Change' in c]
        change_col = change_cols[0] if change_cols else score_col

        # 2. 标题和排序逻辑
        is_gamma = mode in ['topg', 'changeg']
        if mode == 'top':
            title, metric_label, display_col, unit = "Fintel 做空挤压榜 Top 30", "评分", score_col, ""
            df_sorted = df.sort_values(by=score_col, ascending=False).head(30)
            sec_label = "做空"
        elif mode == 'change':
            title, metric_label, display_col, unit = "做空增幅榜 (SI Change) Top 30", "变化", change_col, "%"
            df_sorted = df.sort_values(by=change_col, ascending=False).head(30)
            sec_label = "做空"
        elif mode == 'topg':
            title, metric_label, display_col, unit = "Gamma Squeeze 榜 Top 30", "评分", score_col, ""
            df_sorted = df.sort_values(by=score_col, ascending=False).head(30)
            sec_label = "GEX/PCR"
        elif mode == 'changeg':
            title, metric_label, display_col, unit = "Gamma 增幅榜 Top 30", "变化", change_col, "%"
            df_sorted = df.sort_values(by=change_col, ascending=False).head(30)
            sec_label = "GEX/PCR"
        elif mode == 'topo':
            title, metric_label, display_col, unit = "Option Flow 榜 (Net Premium) Top 30", "金额", score_col, "M"
            df_sorted = df.sort_values(by=score_col, ascending=False).head(30)
            sec_label = "指标"
        elif mode == 'changeo':
            title, metric_label, display_col, unit = "Option Flow 增幅榜 Top 30", "变化", change_col, "%"
            df_sorted = df.sort_values(by=change_col, ascending=False).head(30)
            sec_label = "指标"

        prefix = "📢 **[定时推送]** " if is_scheduled else "🔥 "
        msg = f"{prefix}**{title}**\n"
        msg += f"📅 {datetime.now(self.tz).strftime('%Y-%m-%d %H:%M')} CT\n\n"

        # 表头
        msg += f"`顺序 | 股票   | {metric_label.ljust(4)} | {sec_label.ljust(6)}` \n"
        msg += "`───|────────|──────|──────────` \n"

        for i, (_, row) in enumerate(df_sorted.iterrows(), 1):
            rank = f"{i:02d}"
            ticker = str(row.get('Security', 'Unknown')).split(' / ')[0].strip().upper()
            
            # 主数值格式化
            try:
                raw_val = float(pd.to_numeric(row.get(display_col, 0), errors='coerce'))
                if mode == 'topo' and abs(raw_val) > 1000:
                    val_str = f"{raw_val/1000000:>5.1f}{unit}"
                else:
                    val_str = f"{raw_val:>5.1f}{unit}"
            except:
                val_str = " N/A "

            # 次要指标格式化 (针对 Gamma 特殊处理)
            if is_gamma:
                try:
                    gex = float(pd.to_numeric(row.get('GEX ($MM)', 0), errors='coerce'))
                    pcr = float(pd.to_numeric(row.get('Put/Call Ratio', 0), errors='coerce'))
                    sec_display = f"{gex:>3.0f}/{pcr:.1f}"
                except:
                    sec_display = " N/A "
            else:
                # 原有的做空占比逻辑
                float_col = 'Short Float' if 'Short Float' in df.columns else df.columns[-1]
                try:
                    s_float = float(pd.to_numeric(row.get(float_col, 0), errors='coerce'))
                    sec_display = f"{s_float:>5.1f}%" if 'Float' in str(float_col) else f"{s_float:>5.1f}"
                except:
                    sec_display = " N/A "
            
            google_link = f"https://www.google.com/finance/quote/{ticker}:NASDAQ"
            msg += f"`{rank} | `[{ticker.ljust(6)}]({google_link})` | {val_str.ljust(4)} | {sec_display}` \n"
            
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

        @self.client.on(events.NewMessage(pattern=r'(?i)/topo$'))
        async def handle_topo(event):
            await event.respond("⏳ 正在拉取 Fintel Option Flow 榜单...")
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(None, self.scraper.run, "https://fintel.io/sofStockLeaderboard")
            await event.respond(self.format_message(df, mode='topo'))

        @self.client.on(events.NewMessage(pattern=r'(?i)/changeo$'))
        async def handle_changeo(event):
            await event.respond("⏳ 正在分析 Option Flow 增幅榜单...")
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(None, self.scraper.run, "https://fintel.io/sofStockLeaderboard")
            await event.respond(self.format_message(df, mode='changeo'))
@self.client.on(events.NewMessage(pattern=r'(?i)/start'))
async def handle_start(event):
    await event.respond("欢迎使用 ShortChunwuBot！\n输入 `/menu` 查看所有可用指令。")

@self.client.on(events.NewMessage(pattern=r'(?i)/menu'))
async def handle_menu(event):
    menu_text = (
        "🛠 **ShortChunwuBot 菜单**\n\n"
        "📊 **做空挤压 (Short Squeeze)**\n"
        "  `/top` - 挤压评分榜前 30\n"
        "  `/change` - 做空月度增幅榜前 30\n\n"
        "📈 **期权挤压 (Gamma Squeeze)**\n"
        "  `/topg` - Gamma 评分榜前 30\n"
        "  `/changeg` - Gamma 增幅榜前 30\n\n"
        "💰 **期权异动 (Option Flow)**\n"
        "  `/topo` - 净权利金 (Net Premium) 榜\n"
        "  `/changeo` - 期权流向增幅榜\n\n"
        "🔍 **快捷查询**\n"
        "  `?代码` - 极速获取 Google Finance 链接\n"
        "  例: `?TSLA` \n\n"
        "⏰ **定时任务**\n"
        "  每天 08:15 & 15:15 CT 自动发送 `/top` 榜单。"
    )
    await event.respond(menu_text)

# 4. 快速个股链接指令 (例如 ?TSLA)

        @self.client.on(events.NewMessage(pattern=r'^\?(\w+)'))
        async def handle_quick_link(event):
            ticker = event.pattern_match.group(1).upper()
            google_link = f"https://www.google.com/finance/quote/{ticker}:NASDAQ"
            message = f"🔍 **[{ticker}]({google_link})**"
            await event.respond(message, link_preview=False)

        await self.client.run_until_disconnected()
