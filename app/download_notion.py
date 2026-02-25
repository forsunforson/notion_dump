import os
import re
import logging
import json
import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
import asyncio
from notion_client import Client
from notion_to_md import NotionToMarkdown
from utils import NotionMapper
from jobs.analyze_notes import AnalyzeNotesJob
from services.git_service import GitService

# Load environment variables
# Force reload to pick up changes in .env file if run interactively/repeatedly
load_dotenv(override=True)

# Suppress httpx logs
logging.getLogger("httpx").setLevel(logging.WARNING)

# Configuration
NOTION_TOKEN = os.getenv("notion_token")
ROOT_PAGE_ID = os.getenv("page_id")
OUTPUT_DIR = "notion_output"
STATE_FILE = ".notion-dump-state.json"
HISTORY_FILE = "notion-dump-history.jsonl"

if not NOTION_TOKEN:
    raise ValueError("Please set notion_token in .env file")

if not ROOT_PAGE_ID:
    raise ValueError("Please set page_id in .env file")

# Initialize clients
notion = Client(auth=NOTION_TOKEN)
converter = NotionToMarkdown(notion, OUTPUT_DIR)

import uuid

def format_uuid(id_str):
    """
    Format a Notion ID string into a standard UUID format (with dashes).
    If it's already a valid UUID, return it normalized.
    If invalid, return as is (though Notion IDs should be valid UUIDs).
    """
    if not id_str:
        return None
    try:
        return str(uuid.UUID(id_str))
    except ValueError:
        return id_str

def extract_page_id(input_str):
    """
    Extract Notion Page ID from URL or raw ID string.
    """
    if not input_str:
        return None
        
    # 1. If it looks like a URL
    if "notion.site" in input_str or "notion.so" in input_str:
        # Extract the last 32 hex characters
        match = re.search(r'([a-fA-F0-9]{32})', input_str)
        if match:
            return match.group(1)
        
    # 2. If it's a raw UUID (with or without dashes)
    try:
        # Remove dashes to check length/hex
        clean_id = input_str.replace("-", "")
        if len(clean_id) == 32 and re.match(r'^[a-fA-F0-9]+$', clean_id):
            return clean_id
    except:
        pass
        
    return input_str

def load_state():
    """Load the last sync time from state file."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
                return state.get("last_sync_time")
        except Exception as e:
            print(f"Error loading state file: {e}")
    return None

def save_state(last_sync_time):
    """Save the last sync time to state file."""
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({"last_sync_time": last_sync_time}, f)
        print(f"State saved: last_sync_time={last_sync_time}")
    except Exception as e:
        print(f"Error saving state file: {e}")

def append_history_log(entry):
    """Append a log entry to the history file."""
    try:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"Warning: Failed to write history log: {e}")


def get_page_metadata(page_id, page_obj=None):
    """Retrieve title and metadata of a Notion page or database."""
    try:
        page = None
        if page_obj:
            if page_obj["object"] == "page":
                page = page_obj
            elif page_obj["object"] == "database":
                db = page_obj
                created_time = db.get("created_time")
                last_edited_time = db.get("last_edited_time")
                title_objs = db.get("title", [])
                title = "".join([t["plain_text"] for t in title_objs]) or "Untitled Database"
                
                return {
                    "title": title, 
                    "created_time": created_time, 
                    "last_edited_time": last_edited_time,
                    "properties": {}, 
                    "type": "database",
                    "page_obj": db
                }
        
        if not page:
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
            "type": "page",
            "page_obj": page
        }
        
    except Exception as e:
        # Check if it's a database
        if "is a database" in str(e) and not page_obj:
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
                    "type": "database",
                    "page_obj": db
                }
            except Exception as db_e:
                print(f"Error retrieving metadata for database {page_id}: {db_e}")
        else:
            print(f"Error retrieving metadata for page {page_id}: {e}")
            
        return {"title": "Unknown", "created_time": None, "last_edited_time": None, "type": "unknown", "page_obj": None}

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

def download_page(page_id, output_dir, parent_filename=None, depth=0, page_obj=None, recursive=True):
    """
    Recursively download a Notion page and its children.
    
    Args:
        page_id (str): The ID of the page to download.
        output_dir (Path): The directory to save the file in.
        parent_filename (str): The filename of the parent page.
        depth (int): Current recursion depth.
        page_obj (dict): Optional pre-fetched page object.
        recursive (bool): Whether to recursively download children.
    """
    global processed_count
    # if processed_count >= MAX_PAGES:
    #     return

    print(f"Processing page: {page_id} (Depth: {depth})...")
    processed_count += 1
    
    # 1. Get Page Metadata
    # Ensure page_id is formatted as standard UUID
    page_id = format_uuid(page_id)
    
    metadata = get_page_metadata(page_id, page_obj=page_obj)
    title = metadata["title"]
    # Update converter cache
    converter.page_titles[page_id] = title
    # created_time = metadata["created_time"] 
    # last_edited_time = metadata.get("last_edited_time")
    # properties = metadata.get("properties", {})
    obj_type = metadata.get("type", "page")
    page_obj = metadata.get("page_obj")
    
    if obj_type == "database":
        print(f"Detected {page_id} is a database. Processing as database...")
        real_db_id, is_linked = resolve_database_id(page_id)
        if recursive:
            process_database(real_db_id, output_dir, parent_filename, depth, is_linked=is_linked)
        return

    # Use Page ID as filename for RAG optimization
    filename = f"{page_id}.md"
    
    # 2. Convert to Markdown
    try:
        md_content = ""
        
        # Add YAML Frontmatter
        if page_obj:
            yaml_dict = NotionMapper.page_to_dict(page_obj)
            
            if parent_filename:
                # Extract ID from filename (remove .md extension) for the link text
                # parent_filename is now just {parent_id}.md
                # We can still keep the title in the link text if we had it, but here we only have filename.
                # For RAG, the link target being the ID is the most important.
                # parent_id = Path(parent_filename).stem
                # Ensure parent_id is also formatted (though it should be if it came from filename)
                # parent_id = format_uuid(parent_id)
                yaml_dict["parent_doc_link"] = parent_filename

            yaml_content = NotionMapper.to_yaml(yaml_dict)
                
            md_content += yaml_content
        
        md_content += f"# {title}\n\n"
        
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
    if not recursive:
        return file_path

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

def sync_incremental(force=False):
    """
    Perform incremental sync using Notion Search API.
    """
    root_output_path = Path(OUTPUT_DIR)
    # Use UTC time in ISO 8601 format with Z suffix
    current_run_start_time = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
    
    last_sync_time = load_state()
    if force:
        print("Force update enabled. Ignoring last sync time.")
        last_sync_time = None
    
    print(f"Starting sync. Current time: {current_run_start_time}")
    if last_sync_time:
        print(f"Last sync time: {last_sync_time}")
    else:
        print("Performing full sync (first run or forced).")

    start_time = time.time()
    stats = {
        "created_count": 0,
        "updated_count": 0,
        "error_count": 0
    }
    details = []

    changed_files = []
    has_more = True
    next_cursor = None
    processed_pages_count = 0
    
    try:
        while has_more:
            query_params = {
                "sort": {"direction": "descending", "timestamp": "last_edited_time"},
                "page_size": 100,
            }
            if next_cursor:
                query_params["start_cursor"] = next_cursor
                
            response = notion.search(**query_params)
            results = response.get("results", [])
            
            for page in results:
                page_id = page["id"]
                last_edited_time = page.get("last_edited_time")
                
                # Check if we should stop processing
                if last_sync_time and last_edited_time <= last_sync_time:
                    print(f"Found page not modified since last sync: {last_edited_time} <= {last_sync_time}. Stopping.")
                    has_more = False # Stop pagination
                    break
                
                # Determine parent filename
                parent_filename = None
                parent = page.get("parent", {})
                if parent.get("type") == "page_id":
                    parent_id = format_uuid(parent.get("page_id"))
                    parent_filename = f"{parent_id}.md"
                elif parent.get("type") == "database_id":
                     parent_id = format_uuid(parent.get("database_id"))
                     parent_filename = f"{parent_id}.md"
                
                # Prepare metadata for logging
                filename = f"{format_uuid(page_id)}.md"
                file_path = root_output_path / filename
                action = "UPDATE" if file_path.exists() else "CREATE"
                
                page_title = "Untitled"
                props = page.get("properties", {})
                # Extract title
                for prop in props.values():
                    if prop["type"] == "title":
                        page_title = "".join([t["plain_text"] for t in prop.get("title", [])])
                        break
                
                # Update converter cache
                converter.page_titles[format_uuid(page_id)] = page_title
                
                # Extract tags (only for pages)
                page_tags = []
                if page["object"] == "page":
                    tags_prop = props.get("Tags") or props.get("tags")
                    if tags_prop and tags_prop.get("type") == "multi_select":
                        try:
                            page_tags = [opt["name"] for opt in tags_prop.get("multi_select", [])]
                        except Exception:
                            pass
                
                page_url = page.get("url")

                # Download page (non-recursive)
                try:
                    saved_path = download_page(page_id, root_output_path, parent_filename=parent_filename, page_obj=page, recursive=False)
                    if saved_path:
                        changed_files.append(saved_path)
                        
                        # Update stats and details
                        if action == "CREATE":
                            stats["created_count"] += 1
                        else:
                            stats["updated_count"] += 1
                            
                        details.append({
                            "id": page_id,
                            "title": page_title,
                            "url": page_url,
                            "tags": page_tags,
                            "action": action
                        })
                        
                    processed_pages_count += 1
                except Exception as e:
                    stats["error_count"] += 1
                    print(f"Error downloading page {page_id}: {e}")
                    raise e

            if not has_more:
                break
                
            next_cursor = response.get("next_cursor")
            has_more = response.get("has_more")
            
        print(f"Sync complete. Processed {processed_pages_count} pages.")
        
        if processed_pages_count == 0 and last_sync_time:
             print("No new changes found.")
             
        # Write history log
        try:
            if stats["created_count"] > 0 or stats["updated_count"] > 0 or stats["error_count"] > 0:
                duration = time.time() - start_time
                log_entry = {
                    "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                    "duration": round(duration, 3),
                    "stats": stats,
                    "details": details
                }
                append_history_log(log_entry)
        except Exception as e:
            print(f"Error processing history log: {e}")

        # Update state
        save_state(current_run_start_time)
        return changed_files
        
    except Exception as e:
        # Also attempt to log partial results if possible
        try:
            if stats["created_count"] > 0 or stats["updated_count"] > 0 or stats["error_count"] > 0:
                duration = time.time() - start_time
                log_entry = {
                    "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                    "duration": round(duration, 3),
                    "stats": stats,
                    "details": details,
                    "status": "failed",
                    "error": str(e)
                }
                append_history_log(log_entry)
        except:
            pass
            
        print(f"Sync failed: {e}")
        # import traceback
        # traceback.print_exc()
        sys.exit(1)

def print_page_markdown(url_or_id):
    """
    Download and print markdown for a specific page to stdout.
    """
    page_id_raw = extract_page_id(url_or_id)
    page_id = format_uuid(page_id_raw)
    
    if not page_id:
        print(f"Error: Could not extract valid Page ID from input: {url_or_id}", file=sys.stderr)
        return

    print(f"Fetching metadata for {page_id}...", file=sys.stderr)
    metadata = get_page_metadata(page_id)
    title = metadata["title"]
    page_obj = metadata["page_obj"]
    
    if not page_obj:
        print(f"Failed to retrieve page object for {page_id}.", file=sys.stderr)
        return

    # Update converter cache
    converter.page_titles[page_id] = title

    md_content = ""
    
    # Add YAML Frontmatter
    if page_obj:
        yaml_dict = NotionMapper.page_to_dict(page_obj)
        yaml_content = NotionMapper.to_yaml(yaml_dict)
        md_content += yaml_content
    
    md_content += f"# {title}\n\n"
    
    print("Converting content...", file=sys.stderr)
    try:
        md_content += converter.convert_page_content(page_id)
        
        print("\n" + "="*40 + " MARKDOWN OUTPUT " + "="*40 + "\n")
        print(md_content)
        print("\n" + "="*97 + "\n")
        
    except Exception as e:
        print(f"Error converting page: {e}", file=sys.stderr)

def main():
    parser = argparse.ArgumentParser(description="Notion Dump with Incremental Sync")
    parser.add_argument("--force", "--full", action="store_true", help="Force full sync, ignoring last sync time.")
    parser.add_argument("--skip-analyze", action="store_true", help="Skip AI analysis of changed files.")
    parser.add_argument("--with-analyze", action="store_true", help="Force enable AI analysis even during full sync.")
    parser.add_argument("--print-url", help="Print Markdown for a specific page URL/ID to stdout without saving.")
    
    args, unknown = parser.parse_known_args()
    
    if args.print_url:
        print_page_markdown(args.print_url)
        return

    should_run_analyze = True
    
    last_sync_time = load_state()
    is_full_sync = args.force or (last_sync_time is None)
    
    if args.skip_analyze:
        should_run_analyze = False
    elif is_full_sync:
        if args.with_analyze:
            should_run_analyze = True
        else:
            print("Full sync detected. Analysis is disabled by default to save tokens. Use --with-analyze to enable.")
            should_run_analyze = False
    
    try:
        git_service = GitService(OUTPUT_DIR)
        git_service.init_repo()
        git_service.pull_latest()
    except Exception as e:
        print(f"Warning: Git service initialization failed: {e}")
        git_service = None

    changed_files = sync_incremental(force=args.force)
    
    if git_service:
        try:
            git_service.sync_changes()
        except Exception as e:
            print(f"Warning: Git sync failed: {e}")

    if changed_files and should_run_analyze:
        job = AnalyzeNotesJob()
        try:
            asyncio.run(job.analyze_changes(changed_files))
        except Exception as e:
            print(f"Error running analyze job: {e}")

if __name__ == "__main__":
    main()
