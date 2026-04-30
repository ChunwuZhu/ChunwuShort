import asyncio
import logging
import os
from bot.handlers import ShortBot
from logging.handlers import RotatingFileHandler

# 获取当前项目路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "bot.log")

# 配置全局日志：同时输出到控制台和文件
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=2), # 5MB 日志滚动
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("Main")

async def main():
    logger.info("系统正在初始化服务...")
    bot = ShortBot()
    await bot.start()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("机器人手动停止。")
    except Exception as e:
        logger.error(f"系统运行崩溃: {e}")
