# ChunwuShort - Fintel 做空监控机器人

基于 Telegram、Fintel 网页抓取和 PostgreSQL 的做空及期权异动监控系统。

主要文档见 `README.md`。

## 运行结构

- `main.py`: Telegram bot 入口，对应 `com.chunwu.shortbot`。
- `scraper_service.py`: Fintel 抓取和入库服务，对应 `com.chunwu.shortscraper`。
- `bot/`: Telegram 命令和菜单逻辑。
- `scraper/`: 基于 `undetected-chromedriver` 的 Fintel 页面抓取模块。
- `utils/`: 配置和数据库模型。
- `fintel_profile/`: 浏览器持久化 Session，本地私有。

## 当前提醒规则

`scraper_service.py` 在 SOUT 新数据入库后立即判断是否推送：

- 时间窗口：`08:30-09:00 CT` 和 `14:30-15:00 CT`
- `Trade Side = BUY`
- `Contract = CALL` 或 `PUT`
- `DTX <= 60`
- `Premium Sigmas > 2`
