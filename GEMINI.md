# ChunwuShort - Fintel 做空监控机器人

这是一个基于 Telegram 和 Fintel API 的做空数据监控项目。它能够实时监听 Telegram 指令并抓取特定股票的 Short Squeeze 评分、做空占比及借贷费率，并自动向指定群组推送报告。

## 项目概览
- **主要技术栈**: Python, Telethon (Telegram API), Requests (Fintel API), Dotenv
- **核心功能**:
  - 使用独立的 Telegram Session (`chunwu_short.session`)。
  - 监听 `/short <TICKER>` 指令并返回做空详情。
  - 启动时自动推送热门股票 (TSLA, GME, AMC, NVDA) 的做空报告。
  - 集成 Fintel API 进行数据采集。

## 快速开始

### 1. 环境准备
确保已安装 Python 3.x，并安装依赖：
```bash
pip install -r requirements.txt
```

### 2. 配置环境变量
在 `.env` 文件中配置以下信息：
- `TELEGRAM_API_ID`: 你的 Telegram API ID
- `TELEGRAM_API_HASH`: 你的 Telegram API Hash
- `FINTEL_API_KEY`: 你的 Fintel API Key
- `TARGET_GROUP_ID`: 消息推送的目标群组 ID

### 3. 运行机器人
```bash
python3 fintel_bot.py
```

## 开发约定
- **Session 管理**: 所有的 Telegram 操作必须使用 `chunwu_short` 作为 session 名称，以确保与其它项目隔离。
- **日志**: 使用标准 `logging` 库记录机器人行为及 API 错误。
- **扩展**: 如需增加定时推送功能，建议引入 `apscheduler`。

## 关键文件说明
- `fintel_bot.py`: 机器人主程序，包含消息监听和数据抓取逻辑。
- `list_groups.py`: 辅助脚本，用于初始化 Session 和列出当前账号加入的群组 ID。
- `.env`: 敏感信息及配置存储（不应提交至版本控制）。
- `chunwu_short.session`: Telegram 授权会话文件。
