import os
import re
import logging
import json
import time
import uuid
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

from app.core.paths import project_root, output_dir
from app.services.notion_service import NotionService
from app.utils.notion_converter import NotionToMarkdown, NotionMapper

logger = logging.getLogger(__name__)

PROJECT_ROOT = project_root()
OUTPUT_DIR = output_dir()
STATE_FILE = PROJECT_ROOT / ".chronofold-state.json"
LEGACY_STATE_FILE = PROJECT_ROOT / ".notion-dump-state.json"
HISTORY_FILE = PROJECT_ROOT / "chronofold-history.jsonl"
LEGACY_HISTORY_FILE = PROJECT_ROOT / "notion-dump-history.jsonl"


class SyncNotionJob:
    def __init__(self):
        self.notion_api = NotionService()
        self.converter = NotionToMarkdown(self.notion_api.get_client(), str(OUTPUT_DIR))
        self.processed_count = 0
    
    @staticmethod
    def format_uuid(id_str: str) -> Optional[str]:
        """Format a Notion ID string into a standard UUID format."""
        if not id_str:
            return None
        try:
            return str(uuid.UUID(id_str))
        except ValueError:
            return id_str
    
    @staticmethod
    def extract_page_id(input_str: str) -> Optional[str]:
        """Extract Notion Page ID from URL or raw ID string."""
        if not input_str:
            return None
        
        if "notion.site" in input_str or "notion.so" in input_str:
            match = re.search(r'([a-fA-F0-9]{32})', input_str)
            if match:
                return match.group(1)
        
        try:
            clean_id = input_str.replace("-", "")
            if len(clean_id) == 32 and re.match(r'^[a-fA-F0-9]+$', clean_id):
                return clean_id
        except:
            pass
        
        return input_str
    
    @staticmethod
    def load_state() -> Optional[str]:
        """Load the last sync time from state file."""
        state_path = STATE_FILE if STATE_FILE.exists() else LEGACY_STATE_FILE
        if state_path.exists():
            try:
                with open(state_path, "r") as f:
                    state = json.load(f)
                    return state.get("last_sync_time")
            except Exception as e:
                logger.error(f"Error loading state file: {e}")
        return None
    
    @staticmethod
    def save_state(last_sync_time: str):
        """Save the last sync time to state file."""
        try:
            with open(STATE_FILE, "w") as f:
                json.dump({"last_sync_time": last_sync_time}, f)
            logger.info(f"State saved: last_sync_time={last_sync_time}")
        except Exception as e:
            logger.error(f"Error saving state file: {e}")
    
    @staticmethod
    def append_history_log(entry: dict):
        """Append a log entry to the history file."""
        try:
            with open(HISTORY_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Failed to write history log: {e}")
    
    async def get_page_metadata(self, page_id: str, page_obj: Optional[dict] = None) -> dict:
        """Retrieve title and metadata of a Notion page or database."""
        # 如果没有传入 page_obj，才去发起网络请求拉取
        if not page_obj:
            page_obj = await self.notion_api.get_page_meta(page_id)
            
        if not page_obj:
            return {"title": "Unknown", "type": "unknown", "page_obj": None}
            
        if page_obj.get("object") == "page":
            props = page_obj.get("properties", {})
            title = "Untitled"
            # 遍历查找 type 为 title 的属性
            for prop in props.values():
                if prop.get("type") == "title":
                    title_array = prop.get("title", [])
                    title = "".join([t.get("plain_text", "") for t in title_array]) or "Untitled"
                    break
                    
            return {
                "title": title,
                "created_time": page_obj.get("created_time"),
                "last_edited_time": page_obj.get("last_edited_time"),
                "properties": props,
                "type": "page",
                "page_obj": page_obj  # 核心修复：必须把原始对象包裹返回
            }
            
        elif page_obj.get("object") == "database":
            db = page_obj
            title_objs = db.get("title", [])
            title = "".join([t.get("plain_text", "") for t in title_objs]) or "Untitled Database"
            return {
                "title": title,
                "created_time": db.get("created_time"),
                "last_edited_time": db.get("last_edited_time"),
                "properties": {},
                "type": "database",
                "page_obj": db
            }
            
        return {"title": "Unknown", "type": "unknown", "page_obj": page_obj}
    
    async def download_page(
        self,
        page_id: str,
        output_dir: Path,
        parent_filename: Optional[str] = None,
        depth: int = 0,
        page_obj: Optional[dict] = None,
        recursive: bool = True
    ) -> Optional[Path]:
        """
        Recursively download a Notion page and its children.
        """
        logger.info(f"Processing page: {page_id} (Depth: {depth})...")
        self.processed_count += 1
        
        page_id = self.format_uuid(page_id)
        
        metadata = await self.get_page_metadata(page_id, page_obj=page_obj)
        title = metadata["title"]
        
        if not title or title.strip().lower() == "unknown":
            logger.info(f"Skipping invalid page {page_id} with title: '{title}'")
            return None
        
        self.converter.page_titles[page_id] = title
        obj_type = metadata.get("type", "page")
        page_obj = metadata.get("page_obj")
        
        if obj_type == "database":
            logger.info(f"Detected {page_id} is a database. Processing as database...")
            real_db_id, is_linked = await self.notion_api.resolve_database_id(page_id)
            if recursive:
                await self.process_database(real_db_id, output_dir, parent_filename, depth, is_linked=is_linked)
            return None
        
        filename = f"{page_id}.md"
        
        try:
            md_content = ""
            
            if page_obj:
                yaml_dict = NotionMapper.page_to_dict(page_obj)
                
                if parent_filename:
                    yaml_dict["parent_doc_link"] = parent_filename
                
                yaml_content = NotionMapper.to_yaml(yaml_dict)
                md_content += yaml_content
            
            md_content += f"# {title}\n\n"
            md_content += self.converter.convert_page_content(page_id)
        except Exception as e:
            logger.error(f"Failed to export page {title} ({page_id}): {e}")
            md_content = f"Error exporting page: {e}"
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = output_dir / filename
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        logger.info(f"Saved: {file_path}")
        
        if not recursive:
            return file_path
        
        blocks = await self.notion_api.get_blocks(page_id)
        
        for block in blocks:
            if block["type"] == "child_page":
                child_id = block["id"]
                await self.download_page(child_id, output_dir, filename, depth + 1)
            
            elif block["type"] == "child_database":
                db_title = block["child_database"]["title"]
                db_id = block["id"]
                logger.info(f"Found child database: {db_title} ({db_id})")
                
                real_db_id, is_linked = await self.notion_api.resolve_database_id(db_id)
                await self.process_database(real_db_id, output_dir, filename, depth + 1, is_linked=is_linked)
        
        return file_path
    
    async def process_database(
        self,
        database_id: str,
        output_dir: Path,
        parent_filename: Optional[str],
        depth: int,
        is_linked: bool = False
    ):
        """Iterate through pages in a database and download them."""
        logger.info(f"Processing database: {database_id}...")
        
        pages = await self.notion_api.query_database(database_id)
        
        for page in pages:
            await self.download_page(page["id"], output_dir, parent_filename, depth)
    
    async def sync_incremental(self, force: bool = False) -> List[Path]:
        """
        Perform incremental sync using Notion Search API.
        """
        root_output_path = OUTPUT_DIR
        current_run_start_time = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        
        last_sync_time = self.load_state()
        if force:
            logger.info("Force update enabled. Ignoring last sync time.")
            last_sync_time = None
        
        logger.info(f"Starting sync. Current time: {current_run_start_time}")
        if last_sync_time:
            logger.info(f"Last sync time: {last_sync_time}")
        else:
            logger.info("Performing full sync (first run or forced).")
        
        start_time = time.time()
        stats = {
            "created_count": 0,
            "updated_count": 0,
            "error_count": 0
        }
        details = []
        changed_files = []
        processed_pages_count = 0
        
        try:
            sort_params = {"direction": "descending", "timestamp": "last_edited_time"}
            
            all_results = await self.notion_api.search(sort=sort_params, page_size=100)
            
            for page in all_results:
                page_id = page["id"]
                last_edited_time = page.get("last_edited_time")
                
                if last_sync_time and last_edited_time <= last_sync_time:
                    logger.info(f"Found page not modified since last sync: {last_edited_time} <= {last_sync_time}. Stopping.")
                    break
                
                parent_filename = None
                parent = page.get("parent", {})
                if parent.get("type") == "page_id":
                    parent_id = self.format_uuid(parent.get("page_id"))
                    parent_filename = f"{parent_id}.md"
                elif parent.get("type") == "database_id":
                    parent_id = self.format_uuid(parent.get("database_id"))
                    parent_filename = f"{parent_id}.md"
                
                filename = f"{self.format_uuid(page_id)}.md"
                file_path = root_output_path / filename
                action = "UPDATE" if file_path.exists() else "CREATE"
                
                page_title = "Untitled"
                props = page.get("properties", {})
                for prop in props.values():
                    if prop["type"] == "title":
                        page_title = "".join([t["plain_text"] for t in prop.get("title", [])])
                        break
                
                self.converter.page_titles[self.format_uuid(page_id)] = page_title
                
                page_tags = []
                if page["object"] == "page":
                    tags_prop = props.get("Tags") or props.get("tags")
                    if tags_prop and tags_prop.get("type") == "multi_select":
                        try:
                            page_tags = [opt["name"] for opt in tags_prop.get("multi_select", [])]
                        except Exception:
                            pass
                
                page_url = page.get("url")
                
                try:
                    saved_path = await self.download_page(
                        page_id, 
                        root_output_path, 
                        parent_filename=parent_filename, 
                        page_obj=page, 
                        recursive=False
                    )
                    if saved_path:
                        changed_files.append(saved_path)
                        
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
                    logger.error(f"Error downloading page {page_id}: {e}")
                    raise e
            
            logger.info(f"Sync complete. Processed {processed_pages_count} pages.")
            
            if processed_pages_count == 0 and last_sync_time:
                logger.info("No new changes found.")
            
            if stats["created_count"] > 0 or stats["updated_count"] > 0 or stats["error_count"] > 0:
                duration = time.time() - start_time
                log_entry = {
                    "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                    "duration": round(duration, 3),
                    "stats": stats,
                    "details": details
                }
                self.append_history_log(log_entry)
            
            self.save_state(current_run_start_time)
            return changed_files
            
        except Exception as e:
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
                self.append_history_log(log_entry)
            
            logger.error(f"Sync failed: {e}")
            raise
    
    async def print_page_markdown(self, url_or_id: str):
        """Download and print markdown for a specific page to stdout."""
        page_id_raw = self.extract_page_id(url_or_id)
        page_id = self.format_uuid(page_id_raw)
        
        if not page_id:
            logger.error(f"Could not extract valid Page ID from input: {url_or_id}")
            return
        
        logger.info(f"Fetching metadata for {page_id}...")
        metadata = await self.get_page_metadata(page_id)
        title = metadata["title"]
        page_obj = metadata.get("page_obj")
        
        if not page_obj:
            logger.error(f"Failed to retrieve page object for {page_id}.")
            return
        
        self.converter.page_titles[page_id] = title
        
        md_content = ""
        
        if page_obj:
            yaml_dict = NotionMapper.page_to_dict(page_obj)
            yaml_content = NotionMapper.to_yaml(yaml_dict)
            md_content += yaml_content
        
        md_content += f"# {title}\n\n"
        
        logger.info("Converting content...")
        try:
            md_content += self.converter.convert_page_content(page_id)
            
            print("\n" + "="*40 + " MARKDOWN OUTPUT " + "="*40 + "\n")
            print(md_content)
            print("\n" + "="*97 + "\n")
            
        except Exception as e:
            logger.error(f"Error converting page: {e}")


def load_state() -> Optional[str]:
    """Module-level function for backward compatibility."""
    return SyncNotionJob.load_state()


def sync_incremental(force: bool = False) -> List[Path]:
    """Module-level function for backward compatibility."""
    job = SyncNotionJob()
    return asyncio.run(job.sync_incremental(force=force))


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Notion Sync Job")
    parser.add_argument("--force", "--full", action="store_true", help="Force full sync")
    parser.add_argument("--print-url", help="Print Markdown for a specific page URL/ID")
    
    args, _ = parser.parse_known_args()
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    job = SyncNotionJob()
    
    if args.print_url:
        asyncio.run(job.print_page_markdown(args.print_url))
    else:
        asyncio.run(job.sync_incremental(force=args.force))
