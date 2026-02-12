# Notion Dump for RAG

A powerful tool to recursively export Notion content (Pages, Databases, Linked Views) into a flat, RAG-friendly Markdown format.

## Features

- **RAG-Optimized Output**: 
  - Filenames use **Notion UUIDs** (e.g., `1e2c9e17-cd88-8039-bc92-efd2521ed7d1.md`) to ensure global uniqueness.
  - Internal links use ID-based references (`[Title](UUID.md)`), avoiding broken links due to renaming.
  - Metadata injection: Every file includes `create_time` and `modify_time` headers.
- **Comprehensive Support**:
  - Recursively downloads child pages and databases.
  - **Linked Databases**: Automatically resolves and exports content from Linked Database Views using `data_sources` API.
  - Handles both Page IDs and Database IDs as root nodes.
- **Robust Error Handling**:
  - Automatically falls back to alternative API endpoints (e.g., `data_sources.query`) when standard queries fail.
  - Skips inaccessible content without crashing the entire process.
- **Batch Processing**: Support exporting multiple root pages/databases in a single run.

## Installation

1. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

1. Create an integration in [Notion Developers](https://www.notion.so/my-integrations) and get your **Internal Integration Token**.
2. Share your target Notion pages/databases with your integration connection.
3. Create a `.env` file in the project root:

   ```env
   # Your Notion Integration Token
   notion_token=secret_xxxxxxxxxxxxxxxxxxxxxxxxxxx

   # Comma-separated list of Page or Database IDs to export
   page_id=c8177e66a6f341418ed2c27a55c9e5a9,105e1f11732641c2bb84974caf8e1f23
   ```

## Usage

Run the main download script:

```bash
python app/download_notion.py
```

### Output Structure

All files are saved in the `notion_output` directory with a flat structure:

```text
notion_output/
├── c8177e66-a6f3-4141-8ed2-c27a55c9e5a9.md  (Root Page)
├── 1e2c9e17-cd88-8039-bc92-efd2521ed7d1.md  (Child Page)
├── 0041a775-409c-4d57-8623-a7b3fb047699.md  (Database Entry)
...
```

### File Content Example

```markdown
parent_doc_link: [c8177e66-a6f3-4141-8ed2-c27a55c9e5a9](c8177e66-a6f3-4141-8ed2-c27a55c9e5a9.md)

# Page Title
create_time: 2023-07-12T01:55:00.000Z
modify_time: 2023-07-13T01:57:00.000Z

Page content here...
```

## Tools

- `app/download_notion.py`: The main recursive downloader.
- `app/inspect_notion_data.py`: A debugging tool to dump raw block data for a specific page/database (useful for inspecting API responses).
- `app/notion_to_md.py`: Handles the conversion from Notion Blocks to Markdown.

## Troubleshooting

- **Invalid request URL**: Usually happens with Linked Databases. The script automatically handles this by switching to the `data_sources` API.
- **404 Not Found**: Ensure the bot integration has access to the specific page/database. You must manually "Add connections" > "Your Integration" on the Notion page.

## Reference

- [Notion API Reference](https://developers.notion.com/reference/intro)
