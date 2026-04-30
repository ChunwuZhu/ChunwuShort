import os
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient

load_dotenv()

API_ID = int(os.getenv('TELEGRAM_API_ID'))
API_HASH = os.getenv('TELEGRAM_API_HASH')
# 这是一个全新的 session 文件名，将保存在当前目录下
SESSION_NAME = 'chunwu_short'

async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    
    print(f"正在尝试建立新 Session: {SESSION_NAME}.session")
    # start() 会处理登录，如果未授权会提示输入手机号和验证码
    await client.start()
    
    if await client.is_user_authorized():
        print("\n✅ 成功！新 Session 已建立并授权。")
        print("\n--- 你的群组和频道列表 ---")
        print(f"{'ID':<15} {'名称'}")
        print("-" * 30)
        async for dialog in client.iter_dialogs():
            if dialog.is_group or dialog.is_channel:
                print(f"{dialog.id:<15} {dialog.title}")
    else:
        print("❌ 授权失败。")
    
    await client.disconnect()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n已取消。")
