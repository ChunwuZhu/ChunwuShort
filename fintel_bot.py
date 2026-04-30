import os
import requests
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv
from telethon import TelegramClient, events

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

# 配置
API_ID = int(os.getenv('TELEGRAM_API_ID'))
API_HASH = os.getenv('TELEGRAM_API_HASH')
SESSION_NAME = 'chunwu_short'
FINTEL_API_KEY = os.getenv('FINTEL_API_KEY')
TARGET_GROUP_ID = int(os.getenv('TARGET_GROUP_ID'))

# Fintel API 基础配置
FINTEL_BASE_URL = "https://api.fintel.io/v1"
HEADERS = {"X-API-KEY": FINTEL_API_KEY}

async def get_fintel_short_data(ticker):
    """从 Fintel 获取做空数据"""
    try:
        # 获取 Short Squeeze 数据
        url = f"{FINTEL_BASE_URL}/short-squeeze/stock/{ticker.upper()}"
        response = requests.get(url, headers=HEADERS)
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Fintel API 错误: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"请求 Fintel 出错: {e}")
        return None

def format_message(ticker, data):
    """格式化推送消息"""
    if not data:
        return f"❌ 未找到 ${ticker.upper()} 的做空数据。"
    
    # 提取字段 (根据 Fintel API 响应结构调整)
    score = data.get('shortSqueezeScore', 'N/A')
    short_interest = data.get('shortInterest', 'N/A')
    float_pct = data.get('shortInterestPctFloat', 'N/A')
    borrow_fee = data.get('borrowFeeRate', 'N/A')
    
    msg = (
        f"🔍 **Fintel 做空监控报告: ${ticker.upper()}**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔥 **挤压评分 (Squeeze Score):** `{score}`\n"
        f"📊 **做空占比 (Short % Float):** `{float_pct}%`\n"
        f"💸 **借贷费率 (Borrow Fee):** `{borrow_fee}%`\n"
        f"📉 **总做空量 (Short Interest):** `{short_interest}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ 更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    return msg

async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()
    logger.info("🤖 机器人已启动，正在监听消息...")

    # 1. 监听群组指令 (例如: /short TSLA)
    @client.on(events.NewMessage(pattern='/short (\w+)'))
    async def handler(event):
        ticker = event.pattern_match.group(1).upper()
        logger.info(f"收到查询指令: {ticker}")
        
        await event.respond(f"⏳ 正在查询 ${ticker} 的 Fintel 数据...")
        data = await get_fintel_short_data(ticker)
        message = format_message(ticker, data)
        await event.respond(message)

    # 2. 定时推送 (示例: 启动时推送一次热门股票)
    hot_tickers = ['TSLA', 'GME', 'AMC', 'NVDA']
    logger.info("发送初始热门股票报告...")
    for ticker in hot_tickers:
        data = await get_fintel_short_data(ticker)
        if data:
            message = format_message(ticker, data)
            await client.send_message(TARGET_GROUP_ID, message)
            await asyncio.sleep(2) # 避免频率过快

    # 保持运行
    await client.run_until_disconnected()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("机器人已停止。")
