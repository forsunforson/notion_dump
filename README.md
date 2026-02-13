# Notion Dump

A robust tool to export Notion pages to Markdown with support for incremental sync, "Link to Page" blocks, and AI-powered content observation.

## Features

*   **Incremental Sync**: Only downloads pages that have changed since the last run.
*   **Markdown Conversion**: Converts Notion blocks (Paragraph, Heading, List, Code, Quote, Callout, Image, etc.) to standard Markdown.
*   **Link to Page Support**: Automatically resolves "Link to Page" blocks to Markdown links, using cached titles or local file metadata.
*   **YAML Frontmatter**: Adds metadata (title, created time, last edited time, tags, etc.) as YAML frontmatter to generated Markdown files.
*   **Print to Console**: Option to print converted Markdown directly to stdout without saving to disk.
*   **Content Observer**: (Optional) AI analysis of changed files.

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
    *(Note: Ensure you have a `requirements.txt` with `notion-client`, `python-dotenv`, `pyyaml`, etc.)*

3.  Configure environment variables:
    Create a `.env` file in the root directory:
    ```env
    notion_token=your_integration_token
    page_id=your_root_page_id
    ```

## Usage

### Standard Sync
Run the main script to start an incremental sync:
```bash
python3 app/download_notion.py
```

### Force Full Sync
To ignore the last sync time and download all pages:
```bash
python3 app/download_notion.py --force
```

### Print Page to Console
To convert a specific Notion page and print the Markdown to the terminal (useful for testing or single-page export):
```bash
python3 app/download_notion.py --print-url <Notion_Page_URL_or_ID>
```

### Skip AI Observer
To skip the AI analysis step:
```bash
python3 app/download_notion.py --skip-observer
```

### Force AI Observer (Full Sync)
By default, the AI Observer is disabled during full syncs (`--force`) to save tokens. To force enable it:
```bash
python3 app/download_notion.py --force --with-observer
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

For more details, check [deploy/README.md](deploy/README.md).

## Architecture

*   `app/download_notion.py`: Main entry point. Handles syncing logic, argument parsing, and orchestrates the download process.
*   `app/notion_to_md.py`: Core logic for converting Notion blocks to Markdown. Includes intelligent title resolution for linked pages.
*   `app/observer.py`: Handles AI observation of changed content.
*   `app/utils.py`: Utility functions for mapping Notion properties and handling data formats.

## Recent Updates

*   **Link to Page Fix**: "Link to Page" blocks are now correctly converted to Markdown links `[Page Title](PageID.md)`.
*   **Optimized Title Resolution**: Page titles are resolved using a 3-layer strategy: Memory Cache -> Local File YAML Frontmatter -> Notion API.
*   **CLI Improvements**: Added `--print-url` for quick single-page exports.
