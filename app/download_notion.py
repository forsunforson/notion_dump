import os
import re
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from notion_client import Client
from notion_to_md import NotionToMarkdown

# Load environment variables
# Force reload to pick up changes in .env file if run interactively/repeatedly
load_dotenv(override=True)

# Suppress httpx logs
logging.getLogger("httpx").setLevel(logging.WARNING)

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
converter = NotionToMarkdown(notion)

import uuid

def format_uuid(id_str):
    """
    Format a Notion ID string into a standard UUID format (with dashes).
    If it's already a valid UUID, return it normalized.
    If invalid, return as is (though Notion IDs should be valid UUIDs).
    """
    try:
        return str(uuid.UUID(id_str))
    except ValueError:
        return id_str

import json

def format_properties(properties):
    """
    Simplify Notion properties for JSON export.
    Extracts the 'value' part based on the property type.
    """
    simple_props = {}
    for name, prop in properties.items():
        prop_type = prop.get("type")
        value = None
        
        if prop_type == "title":
            value = "".join([t["plain_text"] for t in prop.get("title", [])])
        elif prop_type == "rich_text":
            value = "".join([t["plain_text"] for t in prop.get("rich_text", [])])
        elif prop_type == "number":
            value = prop.get("number")
        elif prop_type == "select":
            select = prop.get("select")
            value = select["name"] if select else None
        elif prop_type == "multi_select":
            value = [opt["name"] for opt in prop.get("multi_select", [])]
        elif prop_type == "date":
            date = prop.get("date")
            value = date if date else None
        elif prop_type == "checkbox":
            value = prop.get("checkbox")
        elif prop_type == "url":
            value = prop.get("url")
        elif prop_type == "email":
            value = prop.get("email")
        elif prop_type == "phone_number":
            value = prop.get("phone_number")
        elif prop_type == "formula":
            formula = prop.get("formula")
            value = formula.get(formula.get("type")) if formula else None
        elif prop_type == "relation":
            value = [rel["id"] for rel in prop.get("relation", [])]
        elif prop_type == "status":
            status = prop.get("status")
            value = status["name"] if status else None
        # Add other types as needed, for now dump raw for unknown complex types if needed
        # or just skip/simplify
        
        if value is not None:
            simple_props[name] = value
            
    return simple_props

def get_page_metadata(page_id):
    """Retrieve title and metadata of a Notion page or database."""
    try:
        # First try to retrieve as a page
        page = notion.pages.retrieve(page_id=page_id)
        properties = page.get("properties", {})
        created_time = page.get("created_time")
        last_edited_time = page.get("last_edited_time")
        
        # Title property can have different names, usually "title" or "Name"
        title_prop = properties.get("title") or properties.get("Name")
        
        title = "Untitled"
        if title_prop and "title" in title_prop:
             # Extract plain text from title array
            title = "".join([t["plain_text"] for t in title_prop["title"]])
            
        return {
            "title": title, 
            "created_time": created_time, 
            "last_edited_time": last_edited_time,
            "properties": properties,
            "type": "page"
        }
        
    except Exception as e:
        # Check if it's a database
        if "is a database" in str(e):
            try:
                db = notion.databases.retrieve(database_id=page_id)
                created_time = db.get("created_time")
                last_edited_time = db.get("last_edited_time")
                
                # Database title is a list of rich text objects directly in "title" field
                title_objs = db.get("title", [])
                title = "".join([t["plain_text"] for t in title_objs]) or "Untitled Database"
                
                return {
                    "title": title, 
                    "created_time": created_time, 
                    "last_edited_time": last_edited_time,
                    "properties": {}, # Databases don't have properties in the same way pages do
                    "type": "database"
                }
            except Exception as db_e:
                print(f"Error retrieving metadata for database {page_id}: {db_e}")
        else:
            print(f"Error retrieving metadata for page {page_id}: {e}")
            
        return {"title": "Unknown", "created_time": None, "last_edited_time": None, "type": "unknown"}

# Global counter for processed pages
processed_count = 0
# MAX_PAGES = 5  # Limit removed
# Global set to track used filenames in this run
created_files = set()

def resolve_database_id(block_id):
    """
    Resolve the actual database ID. 
    If it's a linked database, return the source database ID and True.
    Otherwise return the block_id itself and False.
    """
    try:
        db_info = notion.databases.retrieve(database_id=block_id)
        # Check for data_sources (linked database)
        if "data_sources" in db_info and db_info["data_sources"]:
            source_id = db_info["data_sources"][0]["id"]
            print(f"Resolved linked database {block_id} -> {source_id}")
            return source_id, True
        return block_id, False
    except Exception as e:
        print(f"Error resolving database ID for {block_id}: {e}")
        return block_id, False

def download_page(page_id, output_dir, parent_filename=None, depth=0):
    """
    Recursively download a Notion page and its children.
    
    Args:
        page_id (str): The ID of the page to download.
        output_dir (Path): The directory to save the file in.
        parent_filename (str): The filename of the parent page.
        depth (int): Current recursion depth.
    """
    global processed_count
    # if processed_count >= MAX_PAGES:
    #     return

    print(f"Processing page: {page_id} (Depth: {depth})...")
    processed_count += 1
    
    # 1. Get Page Metadata
    # Ensure page_id is formatted as standard UUID
    page_id = format_uuid(page_id)
    
    metadata = get_page_metadata(page_id)
    title = metadata["title"]
    created_time = metadata["created_time"] 
    last_edited_time = metadata.get("last_edited_time")
    properties = metadata.get("properties", {})
    obj_type = metadata.get("type", "page")
    
    if obj_type == "database":
        print(f"Detected {page_id} is a database. Processing as database...")
        real_db_id, is_linked = resolve_database_id(page_id)
        process_database(real_db_id, output_dir, parent_filename, depth, is_linked=is_linked)
        return

    # Use Page ID as filename for RAG optimization
    filename = f"{page_id}.md"
    
    # 2. Convert to Markdown
    try:
        md_content = ""
        if parent_filename:
            # Extract ID from filename (remove .md extension) for the link text
            # parent_filename is now just {parent_id}.md
            # We can still keep the title in the link text if we had it, but here we only have filename.
            # For RAG, the link target being the ID is the most important.
            parent_id = Path(parent_filename).stem
            # Ensure parent_id is also formatted (though it should be if it came from filename)
            parent_id = format_uuid(parent_id)
            md_content += f"parent_doc_link: [{parent_id}]({parent_filename})\n"
        
        # Format properties for JSON dump
        simple_props = format_properties(properties)
        if simple_props:
            md_content += f"properties: {json.dumps(simple_props, ensure_ascii=False)}\n"
            
        md_content += f"\n# {title}\n"
        if created_time:
            md_content += f"create_time: {created_time}\n"
        if last_edited_time:
            md_content += f"modify_time: {last_edited_time}\n"
        md_content += "\n"
        md_content += converter.convert_page_content(page_id)
    except Exception as e:
        print(f"Failed to export page {title} ({page_id}): {e}")
        import traceback
        traceback.print_exc()
        md_content = f"Error exporting page: {e}"

    # 3. Save Markdown File
    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = output_dir / filename
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"Saved: {file_path}")

    # 4. Check for Children (Recursion)
    # if depth >= max_depth:
    #     # print(f"Reached max depth {max_depth}, skipping children of {title}")
    #     return

    # No longer creating subdirectories
    
    has_children = False
    cursor = None
    
    while True:
        try:
            response = notion.blocks.children.list(block_id=page_id, start_cursor=cursor)
            blocks = response.get("results", [])
            
            for block in blocks:
                if block["type"] == "child_page":
                    child_id = block["id"]
                    download_page(child_id, output_dir, filename, depth + 1)
                    
                elif block["type"] == "child_database":
                    # Recursively handle child databases
                    db_title = block["child_database"]["title"]
                    db_id = block["id"]
                    print(f"Found child database: {db_title} ({db_id})")
                    
                    # Resolve real DB ID if it's a linked view
                    real_db_id, is_linked = resolve_database_id(db_id)
                    
                    # Process the database content
                    # We treat database items as children of the current page
                    process_database(real_db_id, output_dir, filename, depth + 1, is_linked=is_linked)
            
            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")
            
        except Exception as e:
            print(f"Error fetching children for {title}: {e}")
            break

def process_database(database_id, output_dir, parent_filename, depth, is_linked=False):
    """
    Iterate through pages in a database and download them.
    """
    print(f"Processing database: {database_id}...")
    cursor = None
    
    # If it's a linked database, prefer data_sources.query
    use_data_sources = is_linked and hasattr(notion, "data_sources")
    
    while True:
        # if processed_count >= MAX_PAGES:
        #     break
        try:
            if use_data_sources:
                 print(f"Using data_sources.query for linked database {database_id}...")
                 response = notion.data_sources.query(
                     data_source_id=database_id,
                     start_cursor=cursor
                 )
            else:
                response = notion.request(
                    path=f"databases/{database_id}/query",
                    method="POST",
                    body={"start_cursor": cursor} if cursor else {}
                )
            
            pages = response.get("results", [])
            
            for page in pages:
                download_page(page["id"], output_dir, parent_filename, depth)
                
            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")
            
        except Exception as e:
            # Fallback logic if primary method failed (e.g. standard query failed, try data_sources)
            # Only apply fallback if we didn't already try data_sources as primary
            if not use_data_sources and "Invalid request URL" in str(e) and hasattr(notion, "data_sources"):
                print(f"Standard query failed, trying data_sources.query for {database_id}...")
                try:
                    response = notion.data_sources.query(
                        data_source_id=database_id,
                        start_cursor=cursor
                    )
                    pages = response.get("results", [])
                    for page in pages:
                        download_page(page["id"], output_dir, parent_filename, depth)
                    
                    if not response.get("has_more"):
                        break
                    cursor = response.get("next_cursor")
                    # If fallback succeeds, maybe switch flag for next iteration? 
                    # But simpler to just continue loop and let fallback trigger again or break
                    # Actually, if fallback works, we should probably stick to it for pagination.
                    # For simplicity, we just continue here.
                    continue 
                except Exception as inner_e:
                    print(f"Fallback to data_sources.query also failed: {inner_e}")
            
            # Add detailed error info
            print(f"Error processing database {database_id}: {e}")
            import traceback
            traceback.print_exc()
            break

def main():
    root_output_path = Path(OUTPUT_DIR)
    
    # Split ROOT_PAGE_ID by comma and strip whitespace
    page_ids = [pid.strip() for pid in ROOT_PAGE_ID.split(",") if pid.strip()]
    
    print(f"Starting download for {len(page_ids)} root pages to {root_output_path.absolute()}")
    
    for page_id in page_ids:
        try:
            # Format UUID just in case
            formatted_id = format_uuid(page_id)
            print(f"\n--- Processing Root Page: {formatted_id} ---")
            download_page(formatted_id, root_output_path, parent_filename=None)
        except Exception as e:
            print(f"Error processing root page {page_id}: {e}")
            import traceback
            traceback.print_exc()
            
    print("\nAll downloads complete!")

if __name__ == "__main__":
    main()
