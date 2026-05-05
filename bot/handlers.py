import logging
import pandas as pd
from datetime import datetime, timedelta
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
        self.tz_ct = timezone('US/Central')
        self.tz_et = timezone('US/Eastern')

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

    def get_filtered_sout(self, side, contract, limit=20, offset=0, dtx_limit=None, sigma_min=None):
        db = SessionLocal()
        try:
            results = (
                db.query(FintelSout)
                .filter(func.upper(FintelSout.metrics['Trade Side'].astext) == side)
                .filter(func.upper(FintelSout.metrics['Contract'].astext) == contract)
                .order_by(FintelSout.id.desc())
                .yield_per(200)
            )
            data = []
            matched = 0
            for r in results:
                m = r.metrics
                if dtx_limit:
                    try:
                        dtx_val = int(pd.to_numeric(m.get('DTX', 999), errors='coerce'))
                        if dtx_val >= dtx_limit:
                            continue
                    except Exception:
                        continue
                if sigma_min:
                    try:
                        sig_val = float(pd.to_numeric(m.get('Premium Sigmas', 0), errors='coerce'))
                        if sig_val < sigma_min:
                            continue
                    except Exception:
                        continue
                if matched < offset:
                    matched += 1
                    continue
                row = dict(m)
                row['Security'] = r.security_name
                data.append(row)
                matched += 1
                if len(data) >= limit:
                    break
            df = pd.DataFrame(data)
            if df.empty: return df
            if 'Time' in df.columns:
                df = df.sort_values(by=['Date', 'Time'], ascending=False)
            return df
        finally:
            db.close()

    def convert_et_to_ct(self, time_str):
        """将 NYC (ET) 时间转换为 CT"""
        try:
            et_time = datetime.strptime(time_str[:5], "%H:%M")
            ct_time = et_time - timedelta(hours=1)
            return ct_time.strftime("%H:%M")
        except:
            return time_str[:5]

    def format_compact_message(self, df, mode='top', is_scheduled=False):
        if df is None or df.empty: return "❌ 暂无数据"
        is_sout = mode.startswith('sout_')
        mapping = {'sout_bc': 'BUY CALL', 'sout_bp': 'BUY PUT', 'sout_sc': 'SELL CALL', 'sout_sp': 'SELL PUT'}
        title = mapping.get(mode, "Fintel 榜单") if is_sout else "Fintel 榜单"
        prefix = "📢 **[定时]** " if is_scheduled else "🔥 "
        msg = f"{prefix}**{title}** ({datetime.now(self.tz_ct).strftime('%H:%M')} CT)\n"
        
        # 统一取 20 条展示
        df_display = df.head(20)
        
        lines = []
        for i, (_, row) in enumerate(df_display.iterrows(), 1):
            full_sec = str(row.get('Security', ''))
            ticker = full_sec.split(' / ')[0].strip().upper()
            if not ticker or ticker == 'UNKNOWN' or ' / ' not in full_sec:
                ticker = str(row.get('Symbol', row.get('Ticker', 'N/A'))).strip().upper().split(':')[0]
            
            google_link = f"https://www.google.com/finance/quote/{ticker}:NASDAQ"
            ticker_link = f"**[{ticker}]({google_link})**"
            
            if is_sout:
                t_et = str(row.get('Time', '--:--'))
                t_ct = self.convert_et_to_ct(t_et)
                p = row.get('Premium Paid ($)', 0)
                if abs(p) >= 1000000: ps = f"{p/1000000:.1f}M"
                elif abs(p) >= 1000: ps = f"{p/1000:.0f}K"
                else: ps = f"{p:.0f}"
                sig = f"{float(pd.to_numeric(row.get('Premium Sigmas', 0), errors='coerce')):.1f}"
                dtx = str(row.get('DTX', '0'))
                strike_val = row.get('Strike Price')
                try:
                    s_v = float(pd.to_numeric(strike_val, errors='coerce'))
                    strike = f"${s_v:g}"
                except:
                    strike = f"${strike_val}" if strike_val else "N/A"
                lines.append(f"`{t_ct}` {ticker_link} `{dtx}d` `{strike}` `{ps}` `s:{sig}`")
            else:
                score_key = 'Short Squeeze Score' if 'Short Squeeze Score' in df.columns else 'Gamma Squeeze Score'
                if score_key not in df.columns and len(df.columns) > 2: score_key = df.columns[2]
                extra_key = 'Short Float' if 'Short Float' in df.columns else 'Put/Call Ratio'
                if extra_key not in df.columns and len(df.columns) > 3: extra_key = df.columns[3]
                try: score = f"{float(pd.to_numeric(row.get(score_key, 0), errors='coerce')):.1f}"
                except: score = "0.0"
                try: extra = f"{float(pd.to_numeric(row.get(extra_key, 0), errors='coerce')):.1f}%"
                except: extra = "0.0%"
                lines.append(f"{i:02d}. {ticker_link} {score} | {extra}")
        return msg + "\n".join(lines)

    def get_menu_text(self):
        return (
            "**ShortChunwuBot 🛠 菜单**\n"
            "───|────────|──────\n"
            "📊 **Short:** /top | /change\n"
            "📈 **Gamma:** /topg | /changeg\n"
            "💰 **Flow:**  /topo\n"
            "🔥 **实时 (Live):**\n"
            "  /bc | /bp | /sc | /sp\n"
            "  /bc3m | /bp3m | /sc3m | /sp3m\n"
            "  /bc3m5s | /bp3m5s | /sc3m5s | /sp3m5s\n"
            "🔍 **Quick:** `?代码` (例: `?TSLA`)\n"
            "───|────────|──────\n"
            "⏰ 08:15 & 15:15 CT 自动推送"
        )

    async def send_scheduled_report(self):
        df = self.get_latest_data(ShortSqueeze)
        if df is not None:
            await self.client.send_message(
                config.TARGET_GROUP_ID,
                self.format_compact_message(df, mode='top', is_scheduled=True),
                buttons=[Button.inline("📋 菜单", b"menu")],
                link_preview=False
            )

    async def start(self):
        await self.client.start(bot_token=config.TELEGRAM_BOT_TOKEN)
        logger.info("🤖 Bot 已启动")

        if config.TARGET_GROUP_ID:
            self.scheduler.add_job(
                self.send_scheduled_report,
                "cron",
                hour=8,
                minute=15,
                timezone=self.tz_ct,
                id="short_report_morning",
                replace_existing=True,
            )
            self.scheduler.add_job(
                self.send_scheduled_report,
                "cron",
                hour=15,
                minute=15,
                timezone=self.tz_ct,
                id="short_report_close",
                replace_existing=True,
            )
            self.scheduler.start()
            logger.info("⏰ 定时推送已启用: 08:15 和 15:15 CT")
        else:
            logger.warning("TARGET_GROUP_ID 未配置，定时推送未启用。")

        @self.client.on(events.NewMessage(pattern=r'^p$'))
        async def handle_menu(event):
            await event.respond(self.get_menu_text(), buttons=[Button.inline("📋 菜单", b"menu")])

        @self.client.on(events.NewMessage(pattern=r'(?i)/start$'))
        async def handle_start(event):
            await event.respond("欢迎！点击下方按钮或输入 `p` 查看指令菜单。", buttons=[Button.inline("📋 菜单", b"menu")])

        @self.client.on(events.NewMessage(pattern=r'(?i)/(top|change|topg|changeg|topo)'))
        async def handle_list(event):
            cmd = event.pattern_match.group(1).lower()
            model = ShortSqueeze if cmd in ['top', 'change'] else (GammaSqueeze if 'g' in cmd else OptionFlow)
            df = self.get_latest_data(model)
            await event.respond(
                self.format_compact_message(df, mode=cmd),
                buttons=[Button.inline("📋 菜单", b"menu")],
                link_preview=False
            )

        @self.client.on(events.NewMessage(pattern=r'(?i)/(bc|bp|sc|sp)(3m5s|3m)?'))
        async def handle_sout(event):
            base_cmd = event.pattern_match.group(1).lower()
            suffix = event.pattern_match.group(2) or ""
            side_map = {'bc': ('BUY', 'CALL'), 'bp': ('BUY', 'PUT'), 'sc': ('SELL', 'CALL'), 'sp': ('SELL', 'PUT')}
            side, contract = side_map[base_cmd]
            dtx_limit = 100 if '3m' in suffix else None
            sigma_min = 5.0 if '5s' in suffix else None
            df = self.get_filtered_sout(side, contract, limit=20, offset=0, dtx_limit=dtx_limit, sigma_min=sigma_min)
            buttons = [
                [Button.inline("下一页 ⬇️", f"page_{base_cmd}{suffix}_20".encode())],
                [Button.inline("📋 菜单", b"menu")]
            ]
            await event.respond(self.format_compact_message(df, mode=f'sout_{base_cmd}'), buttons=buttons, link_preview=False)

        @self.client.on(events.CallbackQuery(pattern=r'menu'))
        async def handle_menu_callback(event):
            await event.respond(self.get_menu_text(), buttons=[Button.inline("📋 菜单", b"menu")])
            await event.answer()

        @self.client.on(events.CallbackQuery(pattern=r'page_(\w+)_(\d+)'))
        async def handle_pagination(event):
            cmd_raw = event.data.decode().split('_')[1]
            offset = int(event.data.decode().split('_')[2])
            suffix = ""
            if '3m5s' in cmd_raw: suffix = '3m5s'
            elif '3m' in cmd_raw: suffix = '3m'
            base_cmd = cmd_raw.replace(suffix, '')
            side_map = {'bc': ('BUY', 'CALL'), 'bp': ('BUY', 'PUT'), 'sc': ('SELL', 'CALL'), 'sp': ('SELL', 'PUT')}
            side, contract = side_map[base_cmd]
            dtx_limit = 100 if '3m' in suffix else None
            sigma_min = 5.0 if '5s' in suffix else None
            df = self.get_filtered_sout(side, contract, limit=20, offset=offset, dtx_limit=dtx_limit, sigma_min=sigma_min)
            if df is None or df.empty:
                await event.answer("没有更多数据了", alert=True)
                return
            buttons = []
            row = []
            if offset >= 20:
                row.append(Button.inline("上一页 ⬆️", f"page_{cmd_raw}_{max(0, offset-20)}".encode()))
            row.append(Button.inline("下一页 ⬇️", f"page_{cmd_raw}_{offset+20}".encode()))
            buttons.append(row)
            buttons.append([Button.inline("📋 菜单", b"menu")])
            await event.edit(self.format_compact_message(df, mode=f'sout_{base_cmd}'), buttons=buttons, link_preview=False)
            await event.answer()

        @self.client.on(events.NewMessage(pattern=r'^\?(\w+)'))
        async def handle_quick_link(event):
            ticker = event.pattern_match.group(1).upper()
            await event.respond(
                f"🔍 **[{ticker}](https://www.google.com/finance/quote/{ticker}:NASDAQ)**",
                buttons=[Button.inline("📋 菜单", b"menu")],
                link_preview=False
            )

        try:
            await self.client.run_until_disconnected()
        finally:
            if self.scheduler.running:
                self.scheduler.shutdown(wait=False)
