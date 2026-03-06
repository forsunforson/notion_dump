# ChronoFold

A robust tool to export Notion pages to Markdown with support for incremental sync, "Link to Page" blocks, AI-powered content observation, and Telegram notifications.

## Features

*   **Incremental Sync**: Only downloads pages that have changed since the last run.
*   **Markdown Conversion**: Converts Notion blocks (Paragraph, Heading, List, Code, Quote, Callout, Image, etc.) to standard Markdown.
*   **Link to Page Support**: Automatically resolves "Link to Page" blocks to Markdown links, using cached titles or local file metadata.
*   **YAML Frontmatter**: Adds metadata (title, created time, last edited time, tags, etc.) as YAML frontmatter to generated Markdown files.
*   **Print to Console**: Option to print converted Markdown directly to stdout without saving to disk.
*   **Content Analysis**: (Optional) AI analysis of changed files.
*   **Git Backup**: Automatically commits and pushes generated Markdown files to a separate Git repository.
*   **Telegram Notifications**: Send AI-generated morning greetings and weekly reviews to Telegram.
*   **Task Routing**: Support for different job types (sync, morning routine, weekly review) via CLI.

## Installation

1.  Clone the repository:
    ```bash
    git clone https://github.com/your-repo/chronofold.git
    cd chronofold
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
    GIT_USER_NAME=ChronoFold Backup Bot
    GIT_USER_EMAIL=bot@example.com
    
    # Telegram Configuration (Optional)
    TELEGRAM_BOT_TOKEN=your_telegram_bot_token
    TELEGRAM_CHAT_ID=your_chat_id
    ```

## Usage

### Job Types

The application now supports different job types via the `--job` parameter:

```bash
python main.py --job <sync|morning|weekly|analyze>
```

### Sync Job (Default)

Run incremental sync to download and analyze changed Notion pages:

```bash
python main.py --job sync
```

Options:
- `--force` or `--full`: Force full sync, ignoring last sync time
- `--skip-analyze`: Skip AI analysis of changed files
- `--with-analyze`: Force enable AI analysis even during full sync

Examples:
```bash
# Incremental sync (default)
python main.py

# Force full sync
python main.py --job sync --force

# Full sync with AI analysis
python main.py --job sync --force --with-analyze
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

### Analyze Job

Run AI analysis on markdown files:

```bash
# Analyze all files in notion_output/
python main.py --job analyze

# Analyze specific files
python main.py --job analyze path/to/file1.md path/to/file2.md
```

This will:
1. Find markdown files (all in notion_output/ or specified paths)
2. Run AI analysis on each file
3. Generate a report in `_reports/` directory

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
0 8 * * * cd /path/to/chronofold && python main.py --job morning

# Weekly review at 9:00 AM every Monday
0 9 * * 1 cd /path/to/chronofold && python main.py --job weekly

# Sync every hour
0 * * * * cd /path/to/chronofold && python main.py --job sync
```

For more details, check [deploy/README.md](deploy/README.md).

## Architecture

*   `main.py`: Main entry point with CLI argument parsing and job routing.
*   `app/download_notion.py`: Core syncing logic for downloading Notion pages.
*   `app/services/llm_service.py`: Unified LLM service for AI interactions.
*   `app/services/git_service.py`: Handles Git operations for the backup repository.
*   `app/services/telegram_service.py`: Handles Telegram message sending.
*   `app/services/prompt_manager.py`: Dynamic prompt loading and template management for AI analysis.
*   `app/jobs/routines.py`: Contains morning routine and weekly review logic.
*   `app/jobs/analyze_notes.py`: Handles AI analysis of changed content.
*   `app/notion_to_md.py`: Core logic for converting Notion blocks to Markdown.
*   `app/utils.py`: Utility functions for mapping Notion properties and handling data formats.
*   `config/`: User configuration directory containing profile and prompt templates.
    *   `config/profile.yaml`: User profile for personalized AI analysis.
    *   `config/templates/`: Prompt templates for different content types (diary, article).

## Prompt Manager & Cognitive Engine

The project includes a flexible prompt management system that enables dynamic AI analysis based on content type:

### Features

*   **Dynamic Template Loading**: Automatically selects appropriate prompt templates based on content type.
*   **YAML Frontmatter Routing**: Uses `title: "Daily Entry"` in frontmatter to route diary content to specialized templates.
*   **User Profile Integration**: Personalizes AI analysis with user profile data from `config/profile.yaml`.
*   **Privacy-First Design**: User configuration is stored in `config/` and excluded from version control.
*   **Automatic Backup**: User profile and templates are backed up to Google Drive via Rclone.

### Template Routing Logic

1.  **Diary Detection**: If the Markdown file has `title: "Daily Entry"` in YAML frontmatter, it uses `config/templates/diary.md`.
2.  **Default**: All other files use `config/templates/article.md`.

### User Profile Structure

Edit `config/profile.yaml` to personalize AI analysis:

```yaml
name: "Your Name"
physical_state:
  energy_level: "normal"
  health_status: "healthy"
recent_focus:
  primary_goals: ["Goal 1", "Goal 2"]
  current_projects: ["Project A"]
preferences:
  communication_style: "concise"
  detail_level: "medium"
```

### Custom Templates

Create or modify templates in `config/templates/`:

*   `diary.md`: Template for daily journal entries
*   `article.md`: Template for general documents

Templates support placeholders:
*   `{profile_data}`: Formatted user profile
*   `{filename}`: Name of the analyzed file
*   `{content}`: Full file content

## Recent Updates

*   **Prompt Manager & Cognitive Engine**: Dynamic prompt loading with YAML frontmatter-based routing for personalized AI analysis.
*   **Privacy-First Config**: User profile and templates moved to `config/` directory, excluded from version control.
*   **Telegram Notifications**: Added support for sending AI-generated messages to Telegram.
*   **Task Routing**: New CLI with `--job` parameter for different task types.
*   **Morning Routine**: AI-generated morning greetings based on recent changes.
*   **Weekly Review**: AI-generated weekly summaries of knowledge base activity.
*   **Link to Page Fix**: "Link to Page" blocks are now correctly converted to Markdown links `[Page Title](PageID.md)`.
*   **Optimized Title Resolution**: Page titles are resolved using a 3-layer strategy: Memory Cache -> Local File YAML Frontmatter -> Notion API.
*   **Git Backup**: Added support for automatic Git backup of the output directory to a separate repository.
