# Repository Guidelines

## Project Structure & Module Organization

This is a Python service repo for Fintel scraping and Telegram delivery.

- `main.py`: Telegram bot entry point, run by `com.chunwu.shortbot`.
- `bot/handlers.py`: Telegram commands, menus, pagination, and scheduled reports.
- `scraper_service.py`: long-running Fintel scraper, database writes, and immediate SOUT alerts.
- `scraper/fintel.py`: Selenium / `undetected-chromedriver` browser automation.
- `utils/config.py`: environment-backed configuration.
- `utils/db.py`: SQLAlchemy models and database initialization.
- `com.chunwu.*.plist`: macOS `launchd` service definitions.
- Runtime files such as `.env`, `*.log`, `*.session`, and `fintel_profile/` are local only.

There is currently no dedicated `tests/` directory.

## Build, Test, and Development Commands

Install dependencies:

```bash
pip install -r requirements.txt
```

Initialize database tables:

```bash
python3 utils/db.py
```

Run services manually:

```bash
python3 main.py
python3 scraper_service.py
```

Validate syntax with the production interpreter:

```bash
/opt/miniconda3/bin/python3.13 -m py_compile main.py bot/handlers.py scraper/fintel.py scraper_service.py utils/config.py utils/db.py
```

Restart launchd services:

```bash
launchctl kickstart -k gui/$(id -u)/com.chunwu.shortbot
launchctl kickstart -k gui/$(id -u)/com.chunwu.shortscraper
```

## Coding Style & Naming Conventions

Use Python 3.13-compatible code, 4-space indentation, and clear snake_case names for functions and variables. Keep service behavior explicit: constants such as alert windows and thresholds should live near the logic that uses them. Prefer SQLAlchemy queries over loading large tables into memory. Keep comments short and useful; avoid documenting obvious assignments.

## Testing Guidelines

No formal test framework is configured. Before committing, run `py_compile` and targeted smoke checks for changed logic. For scraper alert changes, test helpers like `is_sout_alert_match()` and `format_sout_alert_line()` with representative rows. Do not run browser automation unnecessarily during small formatting or documentation edits.

## Commit & Pull Request Guidelines

Recent commits use concise imperative summaries, for example `Add SOUT alerts and update docs` or `Ignore session journal files`. Keep commits focused and avoid bundling runtime logs or local session files. Pull requests should describe behavior changes, list validation commands run, and mention any operational impact such as required service restarts or database constraints.

## Security & Configuration Tips

Never commit `.env`, Telegram sessions, logs, Chrome profiles, or credentials. Required secrets include Telegram API values, bot token, target group ID, database URL, and Fintel credentials. Treat `fintel_profile/` as private local browser state.
