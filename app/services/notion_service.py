import os
import logging
import asyncio
import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from zoneinfo import ZoneInfo
import yaml
from notion_client import Client

logger = logging.getLogger(__name__)


class NotionService:
    def __init__(self, token: Optional[str] = None):
        self.token = token or os.getenv("notion_token") or os.getenv("NOTION_TOKEN")
        if not self.token:
            raise ValueError("Notion token is required. Set NOTION_TOKEN environment variable or pass token parameter.")
        self.client = Client(auth=self.token)
        self._db_title_prop_name_cache: dict[str, str] = {}
    
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

    def _resolve_title_property_name(self, database_id: str) -> str:
        cached = self._db_title_prop_name_cache.get(database_id)
        if cached:
            return cached

        db = self.client.databases.retrieve(database_id=database_id)

        def find_title_prop(properties: dict) -> str | None:
            for prop_name, prop in (properties or {}).items():
                if isinstance(prop, dict) and prop.get("type") == "title":
                    return prop_name
            return None

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

    def _get_local_date_str(self) -> str:
        try:
            profile_path = Path(os.getenv("PROFILE_YAML_PATH") or (Path(__file__).parent.parent.parent / "config" / "profile.yaml"))
            if profile_path.exists():
                profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
                tz_name = profile.get("preferences", {}).get("timezone", "Asia/Shanghai")
            else:
                tz_name = "Asia/Shanghai"
        except Exception:
            tz_name = "Asia/Shanghai"

        tz = ZoneInfo(tz_name)
        local_now = datetime.datetime.now(tz)
        return local_now.strftime("%Y-%m-%d")

    def _get_local_datetime_str(self) -> str:
        try:
            profile_path = Path(os.getenv("PROFILE_YAML_PATH") or (Path(__file__).parent.parent.parent / "config" / "profile.yaml"))
            if profile_path.exists():
                profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
                tz_name = profile.get("preferences", {}).get("timezone", "Asia/Shanghai")
            else:
                tz_name = "Asia/Shanghai"
        except Exception:
            tz_name = "Asia/Shanghai"

        tz = ZoneInfo(tz_name)
        local_now = datetime.datetime.now(tz)
        return local_now.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _build_rich_text(content: str) -> list[dict]:
        return [{"type": "text", "text": {"content": content}}]

    @classmethod
    def _split_text_for_notion(cls, text: str, max_len: int = 1800) -> list[str]:
        if not text:
            return [""]
        chunks: list[str] = []
        i = 0
        while i < len(text):
            chunks.append(text[i : i + max_len])
            i += max_len
        return chunks

    @classmethod
    def _content_to_paragraph_blocks(cls, content: str) -> list[dict]:
        blocks: list[dict] = []
        for chunk in cls._split_text_for_notion(content):
            blocks.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": cls._build_rich_text(chunk)},
                }
            )
        return blocks

    @classmethod
    def _content_to_quote_blocks(cls, content: str) -> list[dict]:
        blocks: list[dict] = []
        for chunk in cls._split_text_for_notion(content):
            blocks.append(
                {
                    "object": "block",
                    "type": "quote",
                    "quote": {"rich_text": cls._build_rich_text(chunk)},
                }
            )
        return blocks

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

    def append_to_daily_inbox(
        self,
        content: str,
        source: str = "Telegram",
        category: str = "reflection",
        context_question: str = "",
    ) -> dict:
        database_id = (os.getenv("NOTION_INBOX_DATABASE_ID") or "").strip()
        if not database_id:
            raise ValueError("NOTION_INBOX_DATABASE_ID environment variable is not set")

        local_date = self._get_local_date_str()
        local_datetime = self._get_local_datetime_str()
        page_title = f"{local_date} 碎片记录"

        title_prop_name = self._resolve_title_property_name(database_id)
        db = self.client.databases.retrieve(database_id=database_id)
        props_schema = (db.get("properties", {}) or {})
        if not props_schema and (db.get("data_sources") or []):
            ds_id = (db.get("data_sources") or [{}])[0].get("id")
            if ds_id:
                ds_obj = self.client.request(path=f"data_sources/{ds_id}", method="GET")
                props_schema = (ds_obj.get("properties", {}) or {})

        page_id = None
        page_url = None

        try:
            filter_params = {
                "property": title_prop_name,
                "title": {"contains": local_date}
            }
            results = asyncio.run(self.query_database(database_id, filter_params))
            for page in results:
                props = page.get("properties", {})
                title_prop = props.get(title_prop_name) or props.get("title")
                if title_prop and "title" in title_prop:
                    title_text = "".join([t["plain_text"] for t in title_prop["title"]])
                    if local_date in title_text:
                        page_id = page.get("id")
                        page_url = page.get("url")
                        logger.info(f"Found existing daily page for {local_date}: {page_id}")
                        break
        except Exception as e:
            logger.warning(f"Error searching for daily page: {e}")

        if not page_id:
            try:
                captured_at = self._utc_now_iso()
                properties: dict[str, Any] = {
                    title_prop_name: {"title": self._build_rich_text(page_title)}
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

                page = self.client.pages.create(
                    parent={"database_id": database_id},
                    properties=properties,
                )
                page_id = page.get("id")
                page_url = page.get("url")
                logger.info(f"Created new daily page for {local_date}: {page_id}")
            except Exception as e:
                logger.error(f"Error creating daily page: {e}")
                raise

        raw_content = content if content is not None else ""
        raw_context_question = context_question if context_question is not None else ""

        blocks: list[dict] = []
        time_header = local_datetime.split(" ")[1] if " " in local_datetime else local_datetime
        blocks.append({
            "object": "block",
            "type": "heading_3",
            "heading_3": {
                "rich_text": self._build_rich_text(f"[{time_header}] {category}")
            }
        })
        blocks.append({
            "object": "block",
            "type": "divider"
        })

        if str(raw_context_question).strip():
            blocks.extend(self._content_to_quote_blocks(str(raw_context_question).strip()))

        blocks.extend(self._content_to_paragraph_blocks(raw_content))

        try:
            self.client.blocks.children.append(block_id=page_id, children=blocks)
            logger.info(f"Appended content to daily page {page_id}")
        except Exception as e:
            logger.error(f"Error appending blocks to daily page: {e}")
            raise

        return {"page_id": page_id, "url": page_url, "captured_at": local_datetime}

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
