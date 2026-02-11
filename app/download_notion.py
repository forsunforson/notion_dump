import os
import re
from pathlib import Path
from dotenv import load_dotenv
from notion_client import Client
from notion2markdown import NotionExporter

# Load environment variables
load_dotenv()

# Configuration
NOTION_TOKEN = os.getenv("notion_token")
ROOT_PAGE_ID = os.getenv("page_id")
OUTPUT_DIR = "notion_output"

if not NOTION_TOKEN:
    raise ValueError("Please set notion_token in .env file")

if not ROOT_PAGE_ID:
    raise ValueError("Please set page_id in .env file")

# Initialize clients
notion = Client(auth=NOTION_TOKEN)
exporter = NotionExporter(token=NOTION_TOKEN)

def sanitize_filename(name):
    """Sanitize the filename to be safe for file systems."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def get_page_title(page_id):
    """Retrieve the title of a Notion page."""
    try:
        page = notion.pages.retrieve(page_id=page_id)
        properties = page.get("properties", {})
        
        # Title property can have different names, usually "title" or "Name"
        title_prop = properties.get("title") or properties.get("Name")
        
        if title_prop and "title" in title_prop:
             # Extract plain text from title array
            return "".join([t["plain_text"] for t in title_prop["title"]])
            
        return "Untitled"
    except Exception as e:
        print(f"Error retrieving title for page {page_id}: {e}")
        return "Unknown"

def download_page(page_id, current_output_dir):
    """
    Recursively download a Notion page and its children.
    
    Args:
        page_id (str): The ID of the page to download.
        current_output_dir (Path): The directory to save the file in.
    """
    print(f"Processing page: {page_id}...")
    
    # 1. Get Page Title
    title = get_page_title(page_id)
    safe_title = sanitize_filename(title)
    
    # 2. Convert to Markdown
    try:
        md_content = exporter.export_page(page_id)
    except Exception as e:
        print(f"Failed to export page {title} ({page_id}): {e}")
        md_content = f"Error exporting page: {e}"

    # 3. Save Markdown File
    # Ensure output directory exists
    current_output_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = current_output_dir / f"{safe_title}.md"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"Saved: {file_path}")

    # 4. Check for Children (Recursion)
    # We create a subdirectory with the same name as the page to store its children
    children_dir = current_output_dir / safe_title
    
    has_children = False
    cursor = None
    
    while True:
        try:
            response = notion.blocks.children.list(block_id=page_id, start_cursor=cursor)
            blocks = response.get("results", [])
            
            for block in blocks:
                if block["type"] == "child_page":
                    child_id = block["id"]
                    # If this is the first child, create the directory
                    if not has_children:
                        children_dir.mkdir(exist_ok=True)
                        has_children = True
                    
                    download_page(child_id, children_dir)
                    
                elif block["type"] == "child_database":
                    # Optionally handle databases
                    print(f"Skipping child database in {title}")
            
            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")
            
        except Exception as e:
            print(f"Error fetching children for {title}: {e}")
            break

def main():
    root_output_path = Path(OUTPUT_DIR)
    print(f"Starting download from root page {ROOT_PAGE_ID} to {root_output_path.absolute()}")
    download_page(ROOT_PAGE_ID, root_output_path)
    print("Download complete!")

if __name__ == "__main__":
    main()
