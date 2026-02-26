import os
import logging
import asyncio
from typing import Optional, List, Dict, Any
from notion_client import Client

logger = logging.getLogger(__name__)


class NotionService:
    def __init__(self, token: Optional[str] = None):
        self.token = token or os.getenv("notion_token")
        if not self.token:
            raise ValueError("Notion token is required. Set NOTION_TOKEN environment variable or pass token parameter.")
        self.client = Client(auth=self.token)
    
    def _paginate(self, method, **kwargs) -> List[Dict[str, Any]]:
        """
        Helper method to handle pagination for any Notion API method.
        """
        results = []
        start_cursor = kwargs.pop("start_cursor", None)
        
        while True:
            try:
                if start_cursor:
                    response = method(start_cursor=start_cursor, **kwargs)
                else:
                    response = method(**kwargs)
                
                results.extend(response.get("results", []))
                
                if not response.get("has_more"):
                    break
                    
                start_cursor = response.get("next_cursor")
                
            except Exception as e:
                logger.error(f"Error during pagination: {e}")
                break
        
        return results
    
    async def query_database(
        self, 
        database_id: str, 
        filter_params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Query a Notion database and return all matching pages.
        Handles pagination internally.
        """
        results = []
        start_cursor = None
        
        while True:
            try:
                query_body = {}
                if filter_params:
                    query_body["filter"] = filter_params
                if start_cursor:
                    query_body["start_cursor"] = start_cursor
                
                response = self.client.request(
                    path=f"databases/{database_id}/query",
                    method="POST",
                    body=query_body
                )
                
                results.extend(response.get("results", []))
                
                if not response.get("has_more"):
                    break
                    
                start_cursor = response.get("next_cursor")
                
            except Exception as e:
                if "Invalid request URL" in str(e):
                    try:
                        query_body = {"start_cursor": start_cursor} if start_cursor else {}
                        if filter_params:
                            query_body["filter"] = filter_params
                        
                        response = self.client.data_sources.query(
                            data_source_id=database_id,
                            **query_body
                        )
                        results.extend(response.get("results", []))
                        
                        if not response.get("has_more"):
                            break
                        start_cursor = response.get("next_cursor")
                        continue
                    except Exception as inner_e:
                        logger.error(f"Fallback query also failed: {inner_e}")
                        break
                
                logger.error(f"Error querying database {database_id}: {e}")
                break
        
        return results
    
    async def get_page_meta(self, page_id: str) -> Dict[str, Any]:
        """
        Get metadata for a single page or database.
        Returns a dict with title, created_time, last_edited_time, type, and raw object.
        """
        try:
            page = self.client.pages.retrieve(page_id=page_id)
            properties = page.get("properties", {})
            created_time = page.get("created_time")
            last_edited_time = page.get("last_edited_time")
            
            title_prop = properties.get("title") or properties.get("Name")
            title = "Untitled"
            if title_prop and "title" in title_prop:
                title = "".join([t["plain_text"] for t in title_prop["title"]])
            
            return {
                "title": title,
                "created_time": created_time,
                "last_edited_time": last_edited_time,
                "properties": properties,
                "type": "page",
                "object": page
            }
            
        except Exception as e:
            if "is a database" in str(e):
                try:
                    db = self.client.databases.retrieve(database_id=page_id)
                    title_objs = db.get("title", [])
                    title = "".join([t["plain_text"] for t in title_objs]) or "Untitled Database"
                    
                    return {
                        "title": title,
                        "created_time": db.get("created_time"),
                        "last_edited_time": db.get("last_edited_time"),
                        "properties": {},
                        "type": "database",
                        "object": db
                    }
                except Exception as db_e:
                    logger.error(f"Error retrieving database {page_id}: {db_e}")
            else:
                logger.error(f"Error retrieving page {page_id}: {e}")
        
        return {
            "title": "Unknown",
            "created_time": None,
            "last_edited_time": None,
            "type": "unknown",
            "object": None
        }
    
    async def get_blocks(self, block_id: str) -> List[Dict[str, Any]]:
        """
        Get all blocks for a page or block.
        Handles pagination internally.
        """
        return self._paginate(
            self.client.blocks.children.list,
            block_id=block_id
        )
    
    async def search(
        self,
        query: Optional[str] = None,
        sort: Optional[Dict[str, Any]] = None,
        filter_params: Optional[Dict[str, Any]] = None,
        page_size: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Search Notion and return all results.
        Handles pagination internally.
        """
        results = []
        start_cursor = None
        
        while True:
            try:
                query_params = {"page_size": page_size}
                if query:
                    query_params["query"] = query
                if sort:
                    query_params["sort"] = sort
                if filter_params:
                    query_params["filter"] = filter_params
                if start_cursor:
                    query_params["start_cursor"] = start_cursor
                
                response = self.client.search(**query_params)
                results.extend(response.get("results", []))
                
                if not response.get("has_more"):
                    break
                    
                start_cursor = response.get("next_cursor")
                
            except Exception as e:
                logger.error(f"Error during search: {e}")
                break
        
        return results
    
    async def resolve_database_id(self, block_id: str) -> tuple:
        """
        Resolve the actual database ID.
        If it's a linked database, return the source database ID and True.
        Otherwise return the block_id itself and False.
        """
        try:
            db_info = self.client.databases.retrieve(database_id=block_id)
            if "data_sources" in db_info and db_info["data_sources"]:
                source_id = db_info["data_sources"][0]["id"]
                logger.info(f"Resolved linked database {block_id} -> {source_id}")
                return source_id, True
            return block_id, False
        except Exception as e:
            logger.error(f"Error resolving database ID for {block_id}: {e}")
            return block_id, False
    
    def get_client(self) -> Client:
        """
        Get the underlying Notion client for advanced usage.
        """
        return self.client
