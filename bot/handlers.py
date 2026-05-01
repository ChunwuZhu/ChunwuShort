import logging
import asyncio
import pandas as pd
from datetime import datetime
from telethon import TelegramClient, events, Button
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
            results = db.query(model_class).filter(model_class.scraped_at == latest_time).order_by(model_class.rank.asc()).all()
            data = []
            for r in results:
                if model_class == ShortSqueeze:
                    data.append({'Rank': r.rank, 'Security': r.security_name, 'Short Squeeze Score': float(r.score or 0), 'Short Float': float(r.short_float_pct or 0), 'SI Change': float(r.si_change_1m_pct or 0)})
                elif model_class == GammaSqueeze:
                    data.append({'Rank': r.rank, 'Security': r.security_name, 'Gamma Squeeze Score': float(r.score or 0), 'GEX ($MM)': float(r.gex_mm or 0), 'Put/Call Ratio': float(r.put_call_ratio or 0)})
                elif model_class == OptionFlow:
                    data.append({'Rank': r.rank, 'Security': r.security_name, 'Net Premium': float(r.net_premium or 0), 'Put/Call Ratio': float(r.put_call_ratio or 0)})
            return pd.DataFrame(data)
        finally:
            db.close()

    def get_filtered_sout(self, side, contract, limit=30, offset=0):
        db = SessionLocal()
        try:
            latest_time = db.query(func.max(FintelSout.scraped_at)).scalar()
            if not latest_time: return None
            # 按时间倒序
            results = db.query(FintelSout).filter(FintelSout.scraped_at == latest_time).order_by(FintelSout.id.desc()).all()
            data = []
            for r in results:
                m = r.metrics
                if str(m.get('Trade Side')).upper() == side and str(m.get('Contract')).upper() == contract:
                    row = dict(m)
                    row['Security'] = r.security_name
                    data.append(row)
            df = pd.DataFrame(data)
            if df.empty: return df
            return df.iloc[offset:offset+limit]
        finally:
            db.close()

    def format_compact_message(self, df, mode='top', is_scheduled=False):
        if df is None or df.empty: return "❌ 暂无数据"
        
        is_sout = mode.startswith('sout_')
        mapping = {'sout_bc': 'BUY CALL', 'sout_bp': 'BUY PUT', 'sout_sc': 'SELL CALL', 'sout_sp': 'SELL PUT'}
        title = mapping.get(mode, "Fintel 榜单") if is_sout else "Fintel 榜单"
        
        prefix = "📢 **[定时]** " if is_scheduled else "🔥 "
        msg = f"{prefix}**{title}** ({datetime.now(self.tz).strftime('%H:%M')} CT)\n"
        
        lines = []
        for i, (_, row) in enumerate(df.iterrows(), 1):
            ticker = str(row.get('Security', 'Unknown')).split(' / ')[0].strip().upper()
            google_link = f"https://www.google.com/finance/quote/{ticker}:NASDAQ"
            
            if is_sout:
                t = str(row.get('Time', '--:--'))[:5]
                p = row.get('Premium Paid ($)', 0)
                if abs(p) >= 1000000: ps = f"{p/1000000:.1f}M"
                elif abs(p) >= 1000: ps = f"{p/1000:.0f}K"
                else: ps = f"{p:.0f}"
                sig = f"{float(pd.to_numeric(row.get('Premium Sigmas', 0), errors='coerce')):.1f}"
                dtx = str(row.get('DTX', '0'))
                lines.append(f"{t} **[{ticker}]({google_link})** {dtx}d {ps} s:{sig}")
            else:
                # 针对 Top 榜单做紧凑处理
                score = f"{float(pd.to_numeric(row.iloc[2], errors='coerce')):.1f}"
                extra = f"{float(pd.to_numeric(row.iloc[3], errors='coerce')):.1f}%"
                lines.append(f"{i:02d}. **[{ticker}]({google_link})** {score} | {extra}")
        
        return msg + "\n".join(lines)

    async def send_scheduled_report(self):
        df = self.get_latest_data(ShortSqueeze)
        if df is not None:
            await self.client.send_message(config.TARGET_GROUP_ID, self.format_compact_message(df, mode='top', is_scheduled=True))

    async def start(self):
        await self.client.start(bot_token=config.TELEGRAM_BOT_TOKEN)
        logger.info("🤖 Bot 在线 (紧凑模式)")

        # 菜单
        @self.client.on(events.NewMessage(pattern=r'^1$'))
        async def handle_menu(event):
            await event.respond("**菜单**\n/top /change /topg /changeg /topo\n/bc /bp /sc /sp | `?代码`", buttons=[
                [Button.inline("Buy Call", b"more_bc_0"), Button.inline("Buy Put", b"more_bp_0")],
                [Button.inline("Sell Call", b"more_sc_0"), Button.inline("Sell Put", b"more_sp_0")]
            ])

        # 榜单指令
        @self.client.on(events.NewMessage(pattern=r'(?i)/(top|change|topg|changeg|topo)$'))
        async def handle_list(event):
            cmd = event.pattern_match.group(1).lower()
            model = ShortSqueeze if cmd in ['top', 'change'] else (GammaSqueeze if 'g' in cmd else OptionFlow)
            df = self.get_latest_data(model)
            await event.respond(self.format_compact_message(df, mode=cmd))

        # SOUT 指令 (初始 30 条)
        @self.client.on(events.NewMessage(pattern=r'(?i)/(bc|bp|sc|sp)$'))
        async def handle_sout(event):
            cmd = event.pattern_match.group(1).lower()
            side_map = {'bc': ('BUY', 'CALL'), 'bp': ('BUY', 'PUT'), 'sc': ('SELL', 'CALL'), 'sp': ('SELL', 'PUT')}
            side, contract = side_map[cmd]
            df = self.get_filtered_sout(side, contract, limit=30, offset=0)
            await event.respond(
                self.format_compact_message(df, mode=f'sout_{cmd}'),
                buttons=[Button.inline("More ⬇️", f"more_{cmd}_30".encode())]
            )

        # 处理 More 按钮
        @self.client.on(events.CallbackQuery(pattern=r'more_(\w+)_(\d+)'))
        async def handle_more(event):
            cmd = event.pattern_match.group(1).decode()
            offset = int(event.pattern_match.group(2).decode())
            side_map = {'bc': ('BUY', 'CALL'), 'bp': ('BUY', 'PUT'), 'sc': ('SELL', 'CALL'), 'sp': ('SELL', 'PUT')}
            side, contract = side_map[cmd]
            df = self.get_filtered_sout(side, contract, limit=30, offset=offset)
            if df is None or df.empty:
                await event.answer("没有更多数据了", alert=True)
                return
            await event.respond(
                self.format_compact_message(df, mode=f'sout_{cmd}'),
                buttons=[Button.inline("More ⬇️", f"more_{cmd}_{offset+30}".encode())]
            )
            await event.answer()

        @self.client.on(events.NewMessage(pattern=r'^\?(\w+)'))
        async def handle_quick(event):
            ticker = event.pattern_match.group(1).upper()
            await event.respond(f"🔍 **[{ticker}](https://www.google.com/finance/quote/{ticker}:NASDAQ)**", link_preview=False)

        await self.client.run_until_disconnected()
