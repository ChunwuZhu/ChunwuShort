# A02Info

Unified information bot for Fintel short squeeze, options flow, and manual earnings lookup.

## Services

The project runs as two macOS `launchd` services:

- `com.chunwu.shortbot` runs `main.py`.
  It handles `@ShortChunwuBot` Telegram commands in the configured information group only, reads stored data from PostgreSQL, refreshes the earnings cache every Friday at `15:00` CT, and supports manual earnings lookup.
- `com.chunwu.shortscraper` runs `scraper_service.py`.
  It opens Fintel with `undetected-chromedriver`, keeps Fintel pages loaded, scrapes data during market hours, writes new rows to PostgreSQL, and sends SOUT alerts immediately after new matching rows are inserted.

Keeping the bot and scraper separate lets Telegram command handling continue even if the browser scraper needs to restart.

## Data Collection

During market hours (`08:00-15:30` CT, Monday-Friday), the scraper watches:

- `https://fintel.io/sout`: unusual options trades, checked every minute without page refresh.
- `https://fintel.io/shortSqueeze`: short squeeze leaderboard, refreshed every 30 minutes.
- `https://fintel.io/gammaSqueeze`: gamma squeeze leaderboard, refreshed every 30 minutes.
- `https://fintel.io/sofStockLeaderboard`: option flow leaderboard, refreshed every 30 minutes.

SOUT rows are deduplicated by `data_hash`, based on date, time, symbol, and premium paid.

## Telegram Commands

- `/top`, `/change`: latest Short Squeeze leaderboard.
- `/topg`, `/changeg`: latest Gamma Squeeze leaderboard.
- `/topo`: latest Option Flow leaderboard.
- `/bc`, `/bp`: latest BUY CALL and BUY PUT SOUT rows.
- `/bc3m`, `/bp3m`: SOUT rows with `DTX < 100`.
- `/bc3m5s`, `/bp3m5s`: SOUT rows with `DTX < 100` and `Premium Sigmas >= 5`.
- `/Tday`: manually fetch and push today's US earnings with market cap above `$100B`.
- `/Nday`: manually fetch and push next trading day's US earnings with market cap above `$100B`.
- `?TSLA`: quick Google Finance link for a ticker.
- `p` or `P`: command menu.

All bot commands and callbacks are ignored outside `TARGET_GROUP_ID`.

## Earnings Cache

Earnings data is stored in PostgreSQL tables `earnings_events` and `earnings_cache_dates`.

- The bot refreshes the next two weeks of earnings every Friday at `15:00` CT.
- `/Tday` and `/Nday` read from the database first.
- If the requested date is not cached, the bot fetches that date once, stores it, and replies from the cache.
- Dates with no matching `$100B+` earnings are also marked as cached, so empty results do not trigger repeated API calls.
- Duplicate rows are prevented by a unique key on `report_date`, `ticker`, and `report_time`.

## Automatic Alerts

The scraper sends immediate Telegram alerts only for new SOUT rows inserted during these CT windows:

- `08:30-09:00`: first 30 minutes after market open, `Premium Sigmas > 2`.
- `09:00-14:30`: regular session, `Premium Sigmas > 6`.
- `14:30-15:00`: last 30 minutes before market close, `Premium Sigmas > 2`.

Alert filters:

- `Trade Side = BUY`
- `Contract = CALL` or `PUT`
- `DTX < 65`

## Setup

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Create `.env`:

   ```bash
   TELEGRAM_API_ID=
   TELEGRAM_API_HASH=
   TELEGRAM_BOT_TOKEN=
   TARGET_GROUP_ID=
   DATABASE_URL=
   FINTEL_USERNAME=
   FINTEL_PASSWORD=
   ```

3. Initialize database tables:

   ```bash
   python3 utils/db.py
   ```

4. Run manually:

   ```bash
   python3 main.py
   python3 scraper_service.py
   ```

## Operations

Restart services:

```bash
launchctl kickstart -k gui/$(id -u)/com.chunwu.shortbot
launchctl kickstart -k gui/$(id -u)/com.chunwu.shortscraper
```

Check service status:

```bash
launchctl print gui/$(id -u)/com.chunwu.shortbot
launchctl print gui/$(id -u)/com.chunwu.shortscraper
```
