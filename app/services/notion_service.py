import os
import logging
import asyncio
import datetime
import threading
import concurrent.futures
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict, Any
from notion_client import Client
import yaml

from app.core.paths import config_dir
from app.utils.notion_meta import extract_title, get_page_meta
from app.utils.text_chunking import split_text_by_length
from app.utils.timezone_utils import load_profile_timezone

logger = logging.getLogger(__name__)


class NotionService:
    def __init__(self, token: Optional[str] = None):
        self.token = token or os.getenv("notion_token") or os.getenv("NOTION_TOKEN")
        if not self.token:
            raise ValueError("Notion token is required. Set NOTION_TOKEN environment variable or pass token parameter.")
        self.client = Client(auth=self.token)
        self._db_title_prop_name_cache: dict[str, str] = {}
        self._db_query_target_cache: dict[str, tuple[str, str]] = {}
        self._db_parent_database_id_cache: dict[str, str] = {}
        self._daily_chat_log_page_cache: dict[str, str] = {}
        self._daily_chat_log_lock = threading.Lock()
        self._daily_chat_log_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=int((os.getenv("NOTION_ASYNC_MAX_WORKERS") or "2").strip() or 2),
            thread_name_prefix="notion-chatlog",
        )
    
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
            meta = get_page_meta(page)
            # Add properties for compatibility
            meta["properties"] = page.get("properties", {})
            return meta
            
        except Exception as e:
            if "is a database" in str(e):
                try:
                    db = self.client.databases.retrieve(database_id=page_id)
                    meta = get_page_meta(db)
                    meta["properties"] = {}
                    return meta
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

    def _resolve_title_property_name(self, database_id: str) -> str:
        cached = self._db_title_prop_name_cache.get(database_id)
        if cached:
            return cached

        def find_title_prop(properties: dict) -> str | None:
            for prop_name, prop in (properties or {}).items():
                if isinstance(prop, dict) and prop.get("type") == "title":
                    return prop_name
            return None

        target_type, target_id = self._resolve_query_target(database_id)
        if target_type == "data_source":
            ds_obj = self.client.request(path=f"data_sources/{target_id}", method="GET")
            prop_name = find_title_prop(ds_obj.get("properties", {}) or {})
            if prop_name:
                self._db_title_prop_name_cache[database_id] = prop_name
                return prop_name
            raise ValueError(f"Could not find title property in data source {target_id}")

        db = self.client.databases.retrieve(database_id=database_id)

        prop_name = find_title_prop(db.get("properties", {}) or {})
        if prop_name:
            self._db_title_prop_name_cache[database_id] = prop_name
            return prop_name

        data_sources = db.get("data_sources") or []
        if data_sources:
            ds_id = data_sources[0].get("id")
            if ds_id:
                ds_obj = self.client.request(path=f"data_sources/{ds_id}", method="GET")
                prop_name = find_title_prop(ds_obj.get("properties", {}) or {})
                if prop_name:
                    self._db_title_prop_name_cache[database_id] = prop_name
                    return prop_name

        raise ValueError(f"Could not find title property in database {database_id}")

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _build_rich_text(content: str) -> list[dict]:
        return [{"type": "text", "text": {"content": content}}]

    @classmethod
    def _split_text_for_notion(cls, text: str, max_len: int = 1800) -> list[str]:
        return split_text_by_length(text, max_len)

    @classmethod
    def _content_to_blocks(cls, content: str, block_type: str = "paragraph") -> list[dict]:
        blocks: list[dict] = []
        for chunk in cls._split_text_for_notion(content):
            blocks.append(
                {
                    "object": "block",
                    "type": block_type,
                    block_type: {"rich_text": cls._build_rich_text(chunk)},
                }
            )
        return blocks

    @classmethod
    def _content_to_paragraph_blocks(cls, content: str) -> list[dict]:
        return cls._content_to_blocks(content, "paragraph")

    @classmethod
    def _content_to_quote_blocks(cls, content: str) -> list[dict]:
        return cls._content_to_blocks(content, "quote")

    def _load_profile_timezone(self) -> ZoneInfo:
        return load_profile_timezone()

    @staticmethod
    def _build_chatlog_rich_text(role: str, time_str: str, content: str) -> list[dict]:
        prefix = f"{role} [{time_str}]"
        return [
            {"type": "text", "text": {"content": prefix}, "annotations": {"bold": True}},
            {"type": "text", "text": {"content": ": "}},
            {"type": "text", "text": {"content": content or ""}},
        ]

    def _resolve_query_target(self, database_id: str) -> tuple[str, str]:
        cached = self._db_query_target_cache.get(database_id)
        if cached:
            return cached

        try:
            db_obj = self.client.databases.retrieve(database_id=database_id)
        except Exception as e:
            msg = str(e)
            if "Invalid request URL" in msg or "Could not find database with ID" in msg:
                target = ("data_source", database_id)
                self._db_query_target_cache[database_id] = target
                return target
            raise

        data_sources = db_obj.get("data_sources") or []
        if data_sources and isinstance(data_sources[0], dict):
            ds_id = (data_sources[0].get("id") or "").strip()
            if ds_id:
                target = ("data_source", ds_id)
                self._db_query_target_cache[database_id] = target
                return target

        target = ("database", database_id)
        self._db_query_target_cache[database_id] = target
        return target

    def _query_database_sync(
        self,
        database_id: str,
        filter_params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        target_type, target_id = self._resolve_query_target(database_id)
        results: list[dict] = []
        start_cursor = None
        while True:
            query_body: dict[str, Any] = {}
            if filter_params:
                query_body["filter"] = filter_params
            if start_cursor:
                query_body["start_cursor"] = start_cursor
            if target_type == "database":
                response = self.client.request(
                    path=f"databases/{target_id}/query",
                    method="POST",
                    body=query_body,
                )
            else:
                response = self.client.data_sources.query(
                    data_source_id=target_id,
                    **query_body,
                )
            results.extend(response.get("results", []) or [])
            if not response.get("has_more"):
                break
            start_cursor = response.get("next_cursor")
        return results

    def _resolve_pages_parent_database_id(self, database_id: str) -> str:
        cached = self._db_parent_database_id_cache.get(database_id)
        if cached:
            return cached

        try:
            self.client.databases.retrieve(database_id=database_id)
            resolved = database_id
            self._db_parent_database_id_cache[database_id] = resolved
            return resolved
        except Exception:
            pass

        ds_obj = self.client.request(path=f"data_sources/{database_id}", method="GET") or {}
        parent = ds_obj.get("parent") or {}
        resolved = (
            ds_obj.get("database_id")
            or parent.get("database_id")
        )
        if isinstance(resolved, str) and resolved.strip():
            resolved = resolved.strip()
            self._db_parent_database_id_cache[database_id] = resolved
            return resolved
        raise ValueError(
            "NOTION_CHAT_LOGS_DB_ID appears to be a data_source id, but could not resolve database_id for page creation."
        )

    def _ensure_daily_chat_log_page(self, database_id: str, date_str: str) -> str:
        page_title = f"{date_str} 对话实录"
        cached = self._daily_chat_log_page_cache.get(page_title)
        if cached:
            return cached

        parent_database_id = self._resolve_pages_parent_database_id(database_id)
        title_prop_name = self._resolve_title_property_name(parent_database_id)
        pages = self._query_database_sync(
            database_id=database_id,
            filter_params={"property": title_prop_name, "title": {"equals": page_title}},
        )
        if pages:
            page_id = pages[0].get("id")
            if isinstance(page_id, str) and page_id:
                self._daily_chat_log_page_cache[page_title] = page_id
                return page_id

        page = self.client.pages.create(
            parent={"database_id": parent_database_id},
            properties={title_prop_name: {"title": self._build_rich_text(page_title)}},
        )
        page_id = page.get("id")
        if not isinstance(page_id, str) or not page_id:
            raise RuntimeError("Notion returned empty page id for daily chat log page")
        self._daily_chat_log_page_cache[page_title] = page_id
        return page_id

    def _append_to_daily_chat_log_sync(
        self,
        role: str,
        content: str,
        now_local: Optional[datetime.datetime] = None,
    ) -> None:
        database_id = (
            (os.getenv("NOTION_CHAT_LOGS_DB_ID") or os.getenv("NOTION_CHAT_LOGS_DATABASE_ID") or "")
            .strip()
        )
        if not database_id:
            raise ValueError("NOTION_CHAT_LOGS_DB_ID environment variable is not set")

        tz = self._load_profile_timezone()
        now = now_local or datetime.datetime.now(tz)
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")

        role_norm = (role or "").strip()
        if role_norm not in {"User", "Bot"}:
            role_norm = "User" if role_norm.lower() == "user" else "Bot" if role_norm.lower() == "bot" else "User"

        raw_content = content if content is not None else ""

        with self._daily_chat_log_lock:
            page_id = self._ensure_daily_chat_log_page(database_id, date_str)

        prefix = f"{role_norm} [{time_str}]"
        overhead = len(prefix) + 2
        chunk_max = max(200, 1800 - overhead)
        chunks = self._split_text_for_notion(raw_content, max_len=chunk_max)

        children: list[dict] = []
        for i, chunk in enumerate(chunks):
            if i == 0:
                rich_text = self._build_chatlog_rich_text(role_norm, time_str, chunk)
            else:
                rich_text = self._build_rich_text(chunk)
            children.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": rich_text},
                }
            )

        self.client.blocks.children.append(
            block_id=page_id,
            children=children,
        )

    def append_to_daily_chat_log(self, role: str, content: str) -> None:
        def _run():
            try:
                self._append_to_daily_chat_log_sync(role=role, content=content)
            except Exception as e:
                logger.error(f"Failed to append daily chat log: {e}")

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._daily_chat_log_executor.submit(_run)
            return

        loop.run_in_executor(self._daily_chat_log_executor, _run)

    def append_to_inbox(
        self,
        content: str,
        source: str = "Telegram",
        category: str = "reflection",
        context_question: str = "",
    ) -> dict:
        database_id = (os.getenv("NOTION_INBOX_DATABASE_ID") or "").strip()
        if not database_id:
            raise ValueError("NOTION_INBOX_DATABASE_ID environment variable is not set")

        raw_content = content if content is not None else ""
        raw_context_question = context_question if context_question is not None else ""
        title_seed = " ".join(raw_content.strip().split())
        title_prefix = (title_seed[:20] or "Quick Dump").strip()
        captured_at = self._utc_now_iso()
        title = f"{title_prefix} [{captured_at}]"

        title_prop_name = self._resolve_title_property_name(database_id)
        db = self.client.databases.retrieve(database_id=database_id)
        props_schema = (db.get("properties", {}) or {})
        if not props_schema and (db.get("data_sources") or []):
            ds_id = (db.get("data_sources") or [{}])[0].get("id")
            if ds_id:
                ds_obj = self.client.request(path=f"data_sources/{ds_id}", method="GET")
                props_schema = (ds_obj.get("properties", {}) or {})

        properties: dict[str, Any] = {
            title_prop_name: {"title": self._build_rich_text(title)}
        }

        def maybe_set_property(prop_candidates: list[str], prop_value_builder):
            for name in prop_candidates:
                for real_name, prop_def in props_schema.items():
                    if real_name.lower() == name.lower():
                        built = prop_value_builder(prop_def.get("type"))
                        if built is not None:
                            properties[real_name] = built
                        return

        maybe_set_property(
            ["source"],
            lambda t: (
                {"rich_text": self._build_rich_text(source)}
                if t == "rich_text"
                else {"select": {"name": source}}
                if t == "select"
                else None
            ),
        )
        maybe_set_property(
            ["category", "type"],
            lambda t: (
                {"rich_text": self._build_rich_text(category)}
                if t == "rich_text"
                else {"select": {"name": category}}
                if t == "select"
                else {"multi_select": [{"name": category}]}
                if t == "multi_select"
                else None
            ),
        )
        maybe_set_property(
            ["captured_at", "capturedat", "timestamp", "created_at"],
            lambda t: {"date": {"start": captured_at}} if t == "date" else None,
        )

        children: list[dict] = []
        if str(raw_context_question).strip():
            children.extend(self._content_to_quote_blocks(str(raw_context_question).strip()))
        children.extend(self._content_to_paragraph_blocks(raw_content))

        page = self.client.pages.create(
            parent={"database_id": database_id},
            properties=properties,
            children=children,
        )
        return {"page_id": page.get("id"), "url": page.get("url"), "captured_at": captured_at}

    def append_portfolio_ledger(
        self,
        ticker: str,
        action: str,
        price: float,
        quantity: float,
        currency: str,
        total_amount: float,
        notes: str = "",
    ) -> dict:
        database_id = (os.getenv("NOTION_PORTFOLIO_LEDGER_DB_ID") or "").strip()
        if not database_id:
            raise ValueError("NOTION_PORTFOLIO_LEDGER_DB_ID environment variable is not set")

        captured_at = self._utc_now_iso()
        title = f"[{action}] {ticker} - {captured_at[:10]}"

        title_prop_name = self._resolve_title_property_name(database_id)
        db = self.client.databases.retrieve(database_id=database_id)
        props_schema = (db.get("properties", {}) or {})
        if not props_schema and (db.get("data_sources") or []):
            ds_id = (db.get("data_sources") or [{}])[0].get("id")
            if ds_id:
                ds_obj = self.client.request(path=f"data_sources/{ds_id}", method="GET")
                props_schema = (ds_obj.get("properties", {}) or {})

        properties: dict[str, Any] = {
            title_prop_name: {"title": self._build_rich_text(title)}
        }

        def maybe_set_property(prop_candidates: list[str], prop_value_builder):
            for name in prop_candidates:
                for real_name, prop_def in props_schema.items():
                    if real_name.lower() == name.lower():
                        built = prop_value_builder(prop_def.get("type"))
                        if built is not None:
                            properties[real_name] = built
                        return

        maybe_set_property(
            ["date", "trade_date", "transaction_date"],
            lambda t: {"date": {"start": captured_at}} if t == "date" else None,
        )

        maybe_set_property(
            ["ticker", "stock_code", "symbol", "name"],
            lambda t: (
                {"title": self._build_rich_text(ticker)}
                if t == "title"
                else {"rich_text": self._build_rich_text(ticker)}
                if t == "rich_text"
                else None
            ),
        )

        maybe_set_property(
            ["action", "type", "operation", "trade_type"],
            lambda t: {"select": {"name": action}} if t == "select" else None,
        )

        maybe_set_property(
            ["price", "trade_price", "unit_price"],
            lambda t: {"number": round(price, 2)} if t == "number" else None,
        )

        maybe_set_property(
            ["quantity", "shares", "amount", "volume", "num_shares"],
            lambda t: {"number": round(quantity, 2)} if t == "number" else None,
        )

        maybe_set_property(
            ["currency", "币种", "money_type"],
            lambda t: {"select": {"name": currency}} if t == "select" else None,
        )

        maybe_set_property(
            ["total_amount", "total", "total_price", "总金额"],
            lambda t: {"number": round(total_amount, 2)} if t == "number" else None,
        )

        maybe_set_property(
            ["notes", "note", "备注", "remark", "comment"],
            lambda t: {"rich_text": self._build_rich_text(notes)} if t == "rich_text" else None,
        )

        page = self.client.pages.create(
            parent={"database_id": database_id},
            properties=properties,
        )
        return {"page_id": page.get("id"), "url": page.get("url"), "captured_at": captured_at}
