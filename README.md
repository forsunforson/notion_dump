# Notion Dump

Tool to recursively download Notion pages and convert them to Markdown.

## Installation

1. Create a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

1. Create a `.env` file in the root directory (if not exists):
   ```env
   notion_token=your_integration_token
   page_id=your_root_page_id
   ```

## Usage

Run the download script:
```bash
python app/download_notion.py
```

The downloaded Markdown files will be saved in the `notion_output` directory.
