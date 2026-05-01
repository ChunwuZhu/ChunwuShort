import logging
import asyncio
import pandas as pd
from datetime import datetime
from telethon import TelegramClient, events
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pytz import timezone
from utils.config import config
from utils.db import SessionLocal, ShortSqueeze, GammaSqueeze, FintelSout, OptionFlow
from sqlalchemy import func

logger = logging.getLogger(__name__)

class ShortBot:
    def __init__(self):
        self.client = TelegramClient(config.SESSION_NAME, config.API_ID, config.API_HASH)
        self.scheduler = AsyncIOScheduler()
        self.tz = timezone('US/Central')

    def get_latest_data(self, model_class):
        db = SessionLocal()
        try:
            latest_time = db.query(func.max(model_class.scraped_at)).scalar()
            if not latest_time: return None
            results = db.query(model_class).filter(model_class.scraped_at == latest_time).order_by(model_class.id.asc()).all()
            data = []
            for r in results:
                if model_class == ShortSqueeze:
                    data.append({'Rank': r.rank, 'Security': r.security_name, 'Short Squeeze Score': float(r.score or 0), 'Short Float': float(r.short_float_pct or 0), 'SI Change': float(r.si_change_1m_pct or 0)})
                elif model_class == GammaSqueeze:
                    data.append({'Rank': r.rank, 'Security': r.security_name, 'Gamma Squeeze Score': float(r.score or 0), 'GEX ($MM)': float(r.gex_mm or 0), 'Put/Call Ratio': float(r.put_call_ratio or 0)})
                elif model_class == OptionFlow:
                    data.append({'Rank': r.rank, 'Security': r.security_name, 'Net Premium': float(r.net_premium or 0), 'Put/Call Ratio': float(r.put_call_ratio or 0)})
                elif model_class == FintelSout:
                    row = dict(r.metrics)
                    row['Security'] = r.security_name
                    data.append(row)
            return pd.DataFrame(data)
        finally:
            db.close()

    def get_filtered_sout(self, side, contract):
        """从数据库筛选特定类型的 SOUT 数据"""
        db = SessionLocal()
        try:
            latest_time = db.query(func.max(FintelSout.scraped_at)).scalar()
            if not latest_time: return None
            results = db.query(FintelSout).filter(FintelSout.scraped_at == latest_time).order_by(FintelSout.id.desc()).all()
            data = []
            for r in results:
                m = r.metrics
                if str(m.get('Trade Side')).upper() == side and str(m.get('Contract')).upper() == contract:
                    row = dict(m)
                    row['Security'] = r.security_name
                    data.append(row)
            return pd.DataFrame(data)
        finally:
            db.close()

    def format_message(self, df, mode='top', is_scheduled=False):
        if df is None or df.empty:
            return "❌ 数据库暂无数据。请确保抓取服务已启动。"

        is_gamma = mode in ['topg', 'changeg']
        is_option = mode in ['topo', 'changeo']
        is_sout = mode.startswith('sout_')
        
        if mode == 'top':
            title, metric_label, display_col, unit, sec_label, sec_col = "Fintel 做空挤压榜 Top 30", "评分", "Short Squeeze Score", "", "做空", "Short Float"
        elif mode == 'change':
            title, metric_label, display_col, unit, sec_label, sec_col = "做空增幅榜 (SI Change) Top 30", "变化", "SI Change", "%", "做空", "Short Float"
        elif mode == 'topg':
            title, metric_label, display_col, unit, sec_label = "Gamma Squeeze 榜 Top 30", "评分", "Gamma Squeeze Score", "", "GEX/PCR"
        elif mode == 'changeg':
            title, metric_label, display_col, unit, sec_label = "Gamma 增幅榜 Top 30", "变化", "Gamma Squeeze Score", "%", "GEX/PCR"
        elif mode == 'topo':
            title, metric_label, display_col, unit, sec_label, sec_col = "Option Flow 榜 (Net Premium)", "金额", "Net Premium", "M", "PCR", "Put/Call Ratio"
        elif mode == 'changeo':
            title, metric_label, display_col, unit, sec_label, sec_col = "Option Flow 变化榜", "金额", "Net Premium", "M", "PCR", "Put/Call Ratio"
        elif is_sout:
            mapping = {'sout_bc': 'BUY CALL', 'sout_bp': 'BUY PUT', 'sout_sc': 'SELL CALL', 'sout_sp': 'SELL PUT'}
            title = f"实时异动: {mapping.get(mode, 'SOUT')}"
            metric_label, sec_label = "价格", "详情"

        df_sorted = df.head(30) if is_sout else df.sort_values(by=display_col, ascending=False).head(30)
        prefix = "📢 **[定时推送]** " if is_scheduled else "🔥 "
        msg = f"{prefix}**{title}**\n📅 {datetime.now(self.tz).strftime('%Y-%m-%d %H:%M')} CT\n"
        
        if is_sout:
            msg += f"`时间 | 股票   | DTX | 权利金  | Sig ` \n"
            msg += "`─────|────────|─────|──────────|─────` \n"
        else:
            msg += f"`顺序 | 股票   | {metric_label.ljust(4)} | {sec_label.ljust(6)}` \n"
            msg += "`───|────────|──────|──────────` \n"

        for i, (_, row) in enumerate(df_sorted.iterrows(), 1):
            rank = f"{i:02d}"
            ticker = str(row.get('Security', 'Unknown')).split(' / ')[0].strip().upper()
            google_link = f"https://www.google.com/finance/quote/{ticker}:NASDAQ"

            if is_sout:
                time_str = str(row.get('Time', '--:--'))[:5]
                dtx = str(row.get('DTX', '0')).rjust(3)
                premium = row.get('Premium Paid ($)', 0)
                if abs(premium) >= 1000000: prem_str = f"{premium/1000000:>4.1f}M"
                elif abs(premium) >= 1000: prem_str = f"{premium/1000:>4.0f}K"
                else: prem_str = f"{premium:>5.0f}"
                sigmas = f"{float(pd.to_numeric(row.get('Premium Sigmas', 0), errors='coerce')):>4.1f}"
                msg += f"`{time_str} | `[{ticker.ljust(6)}]({google_link})` | {dtx} | {prem_str.rjust(8)} | {sigmas}` \n"
            else:
                try:
                    raw_val = float(pd.to_numeric(row.get(display_col, 0), errors='coerce'))
                    val_str = f"{raw_val/1000000:>5.1f}{unit}" if mode.startswith('topo') and abs(raw_val) > 1000 else f"{raw_val:>5.1f}{unit}"
                except: val_str = str(row.get(display_col, 'N/A'))[:5].ljust(5)

                if is_gamma:
                    try: sec_display = f"{float(row.get('GEX ($MM)', 0)):>3.0f}/{float(row.get('Put/Call Ratio', 0)):.1f}"
                    except: sec_display = " N/A "
                elif is_option:
                    try: sec_display = f"{float(row.get('Put/Call Ratio', 0)):.2f}"
                    except: sec_display = " N/A "
                else:
                    try: sec_display = f"{float(row.get(sec_col, 0)):>5.1f}%"
                    except: sec_display = " N/A "
                msg += f"`{rank} | `[{ticker.ljust(6)}]({google_link})` | {val_str.ljust(4)} | {sec_display}` \n"
        return msg + "\n💡 点击代码查看 Google Finance 详情"

    async def send_scheduled_report(self):
        df = self.get_latest_data(ShortSqueeze)
        if df is not None: await self.client.send_message(config.TARGET_GROUP_ID, self.format_message(df, mode='top', is_scheduled=True))

    async def start(self):
        await self.client.start(bot_token=config.TELEGRAM_BOT_TOKEN)
        logger.info("🤖 ShortChunwuBot 已在线")
        self.scheduler.add_job(self.send_scheduled_report, 'cron', hour=8, minute=15, timezone=self.tz)
        self.scheduler.add_job(self.send_scheduled_report, 'cron', hour=15, minute=15, timezone=self.tz)
        self.scheduler.start()

        @self.client.on(events.NewMessage(pattern=r'^1$'))
        async def handle_menu(event):
            await event.respond(
                "**ShortChunwuBot 🛠 指令菜单**\n"
                "───|────────|──────\n"
                "📊 **做空:** /top | /change\n"
                "📈 **期权:** /topg | /changeg\n"
                "💰 **资金:** /topo | /changeo\n"
                "🔥 **实时异动 (SOUT):**\n"
                "  /bc (B-Call) | /bp (B-Put)\n"
                "  /sc (S-Call) | /sp (S-Put)\n"
                "🔍 **快捷:** `?代码` (例: `?TSLA`)\n"
                "───|────────|──────\n"
                "⏰ 08:15 & 15:15 CT 自动推送"
            )

        @self.client.on(events.NewMessage(pattern=r'(?i)/top$'))
        async def handle_top(event): await event.respond(self.format_message(self.get_latest_data(ShortSqueeze), mode='top'))
        @self.client.on(events.NewMessage(pattern=r'(?i)/change$'))
        async def handle_change(event): await event.respond(self.format_message(self.get_latest_data(ShortSqueeze), mode='change'))
        @self.client.on(events.NewMessage(pattern=r'(?i)/topg$'))
        async def handle_topg(event): await event.respond(self.format_message(self.get_latest_data(GammaSqueeze), mode='topg'))
        @self.client.on(events.NewMessage(pattern=r'(?i)/changeg$'))
        async def handle_changeg(event): await event.respond(self.format_message(self.get_latest_data(GammaSqueeze), mode='changeg'))
        @self.client.on(events.NewMessage(pattern=r'(?i)/topo$'))
        async def handle_topo(event): await event.respond(self.format_message(self.get_latest_data(OptionFlow), mode='topo'))
        @self.client.on(events.NewMessage(pattern=r'(?i)/changeo$'))
        async def handle_changeo(event): await event.respond(self.format_message(self.get_latest_data(OptionFlow), mode='changeo'))
        @self.client.on(events.NewMessage(pattern=r'(?i)/bc$'))
        async def handle_bc(event): await event.respond(self.format_message(self.get_filtered_sout('BUY', 'CALL'), mode='sout_bc'))
        @self.client.on(events.NewMessage(pattern=r'(?i)/bp$'))
        async def handle_bp(event): await event.respond(self.format_message(self.get_filtered_sout('BUY', 'PUT'), mode='sout_bp'))
        @self.client.on(events.NewMessage(pattern=r'(?i)/sc$'))
        async def handle_sc(event): await event.respond(self.format_message(self.get_filtered_sout('SELL', 'CALL'), mode='sout_sc'))
        @self.client.on(events.NewMessage(pattern=r'(?i)/sp$'))
        async def handle_sp(event): await event.respond(self.format_message(self.get_filtered_sout('SELL', 'PUT'), mode='sout_sp'))
        @self.client.on(events.NewMessage(pattern=r'(?i)/start$'))
        async def handle_start(event): await event.respond("欢迎！输入 `1` 查看指令菜单。")
        @self.client.on(events.NewMessage(pattern=r'^\?(\w+)'))
        async def handle_quick_link(event):
            ticker = event.pattern_match.group(1).upper()
            await event.respond(f"🔍 **[{ticker}](https://www.google.com/finance/quote/{ticker}:NASDAQ)**", link_preview=False)

        await self.client.run_until_disconnected()
