# ChunwuShort - Fintel 做空监控机器人

基于 Telegram 和 Fintel 网页抓取的实时做空数据监控系统。

## 项目结构
- `main.py`: 项目入口。
- `bot/`: Telegram 机器人逻辑。
- `scraper/`: 基于 `undetected-chromedriver` 的数据抓取模块。
- `utils/`: 配置管理及工具类。
- `fintel_profile/`: 浏览器持久化 Session（本地私有）。

## 快速开始
1. 安装依赖: `pip install -r requirements.txt`
2. 运行: `python3 main.py`

## 指令
- `/top`: 实时抓取并展示 Fintel Short Squeeze 排行榜。
