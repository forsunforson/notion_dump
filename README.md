# Notion Dump

A robust tool to export Notion pages to Markdown with support for incremental sync, "Link to Page" blocks, AI-powered content observation, and Telegram notifications.

## Features

*   **Incremental Sync**: Only downloads pages that have changed since the last run.
*   **Markdown Conversion**: Converts Notion blocks (Paragraph, Heading, List, Code, Quote, Callout, Image, etc.) to standard Markdown.
*   **Link to Page Support**: Automatically resolves "Link to Page" blocks to Markdown links, using cached titles or local file metadata.
*   **YAML Frontmatter**: Adds metadata (title, created time, last edited time, tags, etc.) as YAML frontmatter to generated Markdown files.
*   **Print to Console**: Option to print converted Markdown directly to stdout without saving to disk.
*   **Content Observer**: (Optional) AI analysis of changed files.
*   **Git Backup**: Automatically commits and pushes generated Markdown files to a separate Git repository.
*   **Telegram Notifications**: Send AI-generated morning greetings and weekly reviews to Telegram.
*   **Task Routing**: Support for different job types (sync, morning routine, weekly review) via CLI.

## Installation

1.  Clone the repository:
    ```bash
    git clone https://github.com/your-repo/notion-dump.git
    cd notion-dump
    ```

2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
    *(Note: Ensure you have a `requirements.txt` with `notion-client`, `python-dotenv`, `pyyaml`, `openai`, `aiohttp`, etc.)*

3.  Configure environment variables:
    Create a `.env` file in the root directory:
    ```env
    notion_token=your_integration_token
    page_id=your_root_page_id
    
    # AI Configuration
    AI_API_KEY=your_openai_api_key
    AI_BASE_URL=https://api.openai.com/v1
    AI_MODEL=gpt-3.5-turbo
    
    # Git Backup Configuration (Optional)
    GIT_REMOTE_URL=git@github.com:your-user/your-backup-repo.git
    GIT_BRANCH=main
    GIT_USER_NAME=Notion Backup Bot
    GIT_USER_EMAIL=bot@example.com
    
    # Telegram Configuration (Optional)
    TELEGRAM_BOT_TOKEN=your_telegram_bot_token
    TELEGRAM_CHAT_ID=your_chat_id
    ```

## Usage

### Job Types

The application now supports different job types via the `--job` parameter:

```bash
python main.py --job <sync|morning|weekly>
```

### Sync Job (Default)

Run incremental sync to download and analyze changed Notion pages:

```bash
python main.py --job sync
```

Options:
- `--force` or `--full`: Force full sync, ignoring last sync time
- `--skip-observer`: Skip AI analysis of changed files
- `--with-observer`: Force enable AI analysis even during full sync

Examples:
```bash
# Incremental sync (default)
python main.py

# Force full sync
python main.py --job sync --force

# Full sync with AI observer
python main.py --job sync --force --with-observer
```

### Morning Routine

Generate and send a morning greeting to Telegram based on recent knowledge base changes:

```bash
python main.py --job morning
```

This will:
1. Read the latest report from `_reports/` directory
2. Use AI to generate a friendly morning message
3. Send the message to your Telegram chat

### Weekly Review

Generate and send a weekly summary to Telegram:

```bash
python main.py --job weekly
```

This will:
1. Collect reports and activity logs from the past 7 days
2. Use AI to generate a comprehensive weekly review
3. Send the summary to your Telegram chat

### Legacy Usage

The original script is still available:

```bash
# Standard sync
python3 app/download_notion.py

# Force full sync
python3 app/download_notion.py --force

# Print page to console
python3 app/download_notion.py --print-url <Notion_Page_URL_or_ID>
```

## Deployment

We provide scripts for easy deployment and scheduling on Linux servers (e.g., GCP VM).

### Quick Start

1.  **Run Interactively**:
    Use the interactive manager to run tasks, schedule cron jobs, or view logs:
    ```bash
    ./deploy/manage.sh
    ```

2.  **Manual Execution**:
    ```bash
    ./deploy/run_task.sh
    ```

### Scheduling with Cron

You can schedule different jobs using cron:

```bash
# Morning routine at 8:00 AM every day
0 8 * * * cd /path/to/notion-dump && python main.py --job morning

# Weekly review at 9:00 AM every Monday
0 9 * * 1 cd /path/to/notion-dump && python main.py --job weekly

# Sync every hour
0 * * * * cd /path/to/notion-dump && python main.py --job sync
```

For more details, check [deploy/README.md](deploy/README.md).

## Architecture

*   `main.py`: Main entry point with CLI argument parsing and job routing.
*   `app/download_notion.py`: Core syncing logic for downloading Notion pages.
*   `app/services/git_service.py`: Handles Git operations for the backup repository.
*   `app/services/telegram_service.py`: Handles Telegram message sending.
*   `app/jobs/routines.py`: Contains morning routine and weekly review logic.
*   `app/notion_to_md.py`: Core logic for converting Notion blocks to Markdown.
*   `app/observer.py`: Handles AI observation of changed content.
*   `app/utils.py`: Utility functions for mapping Notion properties and handling data formats.

## Recent Updates

*   **Telegram Notifications**: Added support for sending AI-generated messages to Telegram.
*   **Task Routing**: New CLI with `--job` parameter for different task types.
*   **Morning Routine**: AI-generated morning greetings based on recent changes.
*   **Weekly Review**: AI-generated weekly summaries of knowledge base activity.
*   **Link to Page Fix**: "Link to Page" blocks are now correctly converted to Markdown links `[Page Title](PageID.md)`.
*   **Optimized Title Resolution**: Page titles are resolved using a 3-layer strategy: Memory Cache -> Local File YAML Frontmatter -> Notion API.
*   **Git Backup**: Added support for automatic Git backup of the output directory to a separate repository.
