from notion_client import Client
from datetime import datetime
import re
import uuid
import os
import yaml
from pathlib import Path

from app.utils.notion_ids import normalize_uuid


class ForceDoubleQuoteStr(str):
    pass


class NotionMapper:
    @staticmethod
    def to_snake_case(text):
        """Convert text to snake_case."""
        if not text:
            return ""
        s = re.sub(r'[^a-zA-Z0-9_]', ' ', text)
        s = s.strip().lower()
        s = re.sub(r'\s+', '_', s)
        return s

    @staticmethod
    def _convert_date(date_str):
        """Convert Notion date string to ISO 8601 format."""
        if not date_str:
            return None
        try:
            if 'T' in date_str:
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            else:
                return date_str
        except ValueError:
            return date_str

    @staticmethod
    def _extract_plain_text(rich_text_list):
        if not rich_text_list:
            return ""
        return "".join([t.get("plain_text", "") for t in rich_text_list])

    @staticmethod
    def map_property(prop):
        prop_type = prop.get("type")
        
        if prop_type == "title":
            return NotionMapper._extract_plain_text(prop.get("title", []))
            
        elif prop_type == "rich_text":
            return NotionMapper._extract_plain_text(prop.get("rich_text", []))
            
        elif prop_type == "number":
            return prop.get("number")
            
        elif prop_type == "select":
            select = prop.get("select")
            return select.get("name") if select else None
            
        elif prop_type == "multi_select":
            options = prop.get("multi_select", [])
            return [opt.get("name") for opt in options]
            
        elif prop_type == "date":
            date_obj = prop.get("date")
            if not date_obj:
                return None
            return date_obj.get("start")
            
        elif prop_type == "checkbox":
            return prop.get("checkbox")
            
        elif prop_type == "url":
            return prop.get("url")
            
        elif prop_type == "email":
            return prop.get("email")
            
        elif prop_type == "phone_number":
            return prop.get("phone_number")
            
        elif prop_type == "people":
            people = prop.get("people", [])
            names = [p.get("name") for p in people if p.get("name")]
            return names if names else []
            
        elif prop_type == "status":
            status = prop.get("status")
            return status.get("name") if status else None
            
        elif prop_type == "files":
            files = prop.get("files", [])
            return [f.get("name") for f in files]
            
        elif prop_type == "formula":
            formula = prop.get("formula")
            if formula:
                f_type = formula.get("type")
                return formula.get(f_type)
            return None
            
        elif prop_type == "relation":
            relations = prop.get("relation", [])
            return [r.get("id") for r in relations]
            
        elif prop_type == "created_time":
            return NotionMapper._convert_date(prop.get("created_time"))
            
        elif prop_type == "last_edited_time":
            return NotionMapper._convert_date(prop.get("last_edited_time"))
            
        elif prop_type == "created_by":
             user = prop.get("created_by")
             return user.get("name") if user else None
             
        elif prop_type == "last_edited_by":
             user = prop.get("last_edited_by")
             return user.get("name") if user else None

        return None

    @staticmethod
    def _wrap_value(value):
        """Wrap string values in ForceDoubleQuoteStr."""
        if isinstance(value, str):
            return ForceDoubleQuoteStr(value)
        elif isinstance(value, list):
            return [NotionMapper._wrap_value(v) for v in value]
        elif isinstance(value, dict):
            return {k: NotionMapper._wrap_value(v) for k, v in value.items()}
        return value

    @staticmethod
    def page_to_dict(page):
        """
        Convert a Notion page object to a dictionary suitable for YAML Frontmatter.
        """
        data = {}
        
        data["id"] = NotionMapper._wrap_value(page.get("id"))
        data["url"] = NotionMapper._wrap_value(page.get("url"))
        data["created_time"] = NotionMapper._wrap_value(NotionMapper._convert_date(page.get("created_time")))
        data["last_edited_time"] = NotionMapper._wrap_value(NotionMapper._convert_date(page.get("last_edited_time")))
        
        properties = page.get("properties", {})
        
        title = "Untitled"
        for key, prop in properties.items():
            if prop.get("type") == "title":
                title = NotionMapper.map_property(prop)
                break
        
        data["title"] = NotionMapper._wrap_value(title)

        for key, prop in properties.items():
            prop_type = prop.get("type")
            if prop_type == "title":
                continue 
            
            if prop_type in ["created_time", "last_edited_time"]:
                continue
            
            yaml_key = NotionMapper.to_snake_case(key)
            value = NotionMapper.map_property(prop)
            
            if value is None:
                continue
            if isinstance(value, list) and len(value) == 0:
                continue
            
            data[yaml_key] = NotionMapper._wrap_value(value)
            
        return data

    @staticmethod
    def to_yaml(data):
        """Convert dictionary to YAML string with --- delimiters."""
        
        def quoted_str_presenter(dumper, data):
            if len(data.splitlines()) > 1:
                return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
            return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='"')

        class QuotedDumper(yaml.SafeDumper):
            pass

        QuotedDumper.add_representer(ForceDoubleQuoteStr, quoted_str_presenter)

        yaml_str = yaml.dump(data, Dumper=QuotedDumper, allow_unicode=True, sort_keys=False, default_flow_style=False)
        return f"---\n{yaml_str}---\n"


class NotionToMarkdown:
    def __init__(self, notion_client: Client, output_dir: str = "notion_output"):
        self.notion = notion_client
        self.output_dir = Path(output_dir)
        self.page_titles = {}

    def _format_uuid(self, id_str):
        """Format a Notion ID string into a standard UUID format (with dashes). (Deprecated)"""
        return normalize_uuid(id_str)

    def _sanitize_filename(self, name):
        """Sanitize the filename to be safe for file systems."""
        name = re.sub(r'[\\/*?:"<>|]', "", name)
        name = name.replace(" ", "_")
        return name.strip()

    def _get_page_date_prefix(self, page_id):
        """Fetch page metadata to get created_time for filename prefix."""
        try:
            page = self.notion.pages.retrieve(page_id=page_id)
            created_time = page.get("created_time")
            if created_time:
                 dt = datetime.fromisoformat(created_time.replace('Z', '+00:00'))
                 return dt.strftime("%Y_%m_%d_")
        except Exception as e:
            print(f"Error fetching metadata for link generation {page_id}: {e}")
        return ""

    def get_page_title(self, page_id):
        """
        Get page title from cache, local file, or Notion API.
        """
        page_id = self._format_uuid(page_id)
        
        if page_id in self.page_titles:
            return self.page_titles[page_id]

        file_path = self.output_dir / f"{page_id}.md"
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read(4096)
                    
                    frontmatter_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
                    if frontmatter_match:
                        try:
                            frontmatter = yaml.safe_load(frontmatter_match.group(1))
                            if isinstance(frontmatter, dict) and "title" in frontmatter:
                                title = str(frontmatter["title"]).strip()
                                self.page_titles[page_id] = title
                                return title
                        except yaml.YAMLError:
                            pass

                    match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
                    if match:
                        title = match.group(1).strip()
                        self.page_titles[page_id] = title
                        return title
            except Exception as e:
                print(f"Warning: Failed to read title from local file {file_path}: {e}")

        try:
            page = self.notion.pages.retrieve(page_id=page_id)
            
            if page.get("object") == "page":
                properties = page.get("properties", {})
                title_prop = properties.get("title") or properties.get("Name")
                
                title = "Untitled"
                if title_prop and "title" in title_prop:
                    title = "".join([t["plain_text"] for t in title_prop["title"]])
                
                self.page_titles[page_id] = title
                return title
            elif page.get("object") == "database":
                 title_objs = page.get("title", [])
                 title = "".join([t["plain_text"] for t in title_objs]) or "Untitled Database"
                 self.page_titles[page_id] = title
                 return title

        except Exception as e:
            print(f"Warning: Failed to fetch title for page {page_id}: {e}")
        
        return None

    def block_to_markdown(self, block):
        block_type = block["type"]
        
        if block_type == "paragraph":
            return self._rich_text_to_md(block["paragraph"]["rich_text"]) + "\n\n"
        
        elif block_type.startswith("heading_"):
            level = int(block_type.split("_")[1])
            text = self._rich_text_to_md(block[block_type]["rich_text"])
            return f"{'#' * level} {text}\n\n"
        
        elif block_type == "bulleted_list_item":
            text = self._rich_text_to_md(block["bulleted_list_item"]["rich_text"])
            return f"- {text}\n"
        
        elif block_type == "numbered_list_item":
            text = self._rich_text_to_md(block["numbered_list_item"]["rich_text"])
            return f"1. {text}\n"
            
        elif block_type == "to_do":
            checked = "x" if block["to_do"]["checked"] else " "
            text = self._rich_text_to_md(block["to_do"]["rich_text"])
            return f"- [{checked}] {text}\n"
            
        elif block_type == "code":
            language = block["code"]["language"]
            text = self._rich_text_to_md(block["code"]["rich_text"])
            return f"```{language}\n{text}\n```\n\n"
            
        elif block_type == "quote":
            text = self._rich_text_to_md(block["quote"]["rich_text"])
            return f"> {text}\n\n"
            
        elif block_type == "callout":
            text = self._rich_text_to_md(block["callout"]["rich_text"])
            icon = block["callout"].get("icon", {}).get("emoji", "")
            return f"> {icon} {text}\n\n"

        elif block_type == "divider":
            return "---\n\n"
            
        elif block_type == "image":
            image_data = block["image"]
            url = ""
            caption = ""
            
            if image_data["type"] == "external":
                url = image_data["external"]["url"]
            elif image_data["type"] == "file":
                url = image_data["file"]["url"]
                
            if image_data.get("caption"):
                caption = self._rich_text_to_md(image_data["caption"])
                
            return f"![{caption}]({url})\n\n"

        elif block_type == "child_page":
            title = block["child_page"]["title"]
            page_id = self._format_uuid(block["id"])
            return f"[{title}]({page_id}.md)\n\n"

        elif block_type == "link_to_page":
            link_info = block["link_to_page"]
            target_id = None
            
            if link_info["type"] == "page_id":
                target_id = link_info["page_id"]
            elif link_info["type"] == "database_id":
                target_id = link_info["database_id"]
            
            if target_id:
                target_id = self._format_uuid(target_id)
                title = self.get_page_title(target_id)
                
                if title:
                    return f"[{title}]({target_id}.md)\n\n"
                else:
                    return f"[Linked Page]({target_id}.md)\n\n"
            return ""
            
        elif block_type == "child_database":
            return ""

        return ""

    def _rich_text_to_md(self, rich_text_list):
        md_text = ""
        for text_obj in rich_text_list:
            content = text_obj["plain_text"]
            annotations = text_obj.get("annotations", {})
            href = text_obj.get("href")
            
            if annotations.get("bold"):
                content = f"**{content}**"
            if annotations.get("italic"):
                content = f"*{content}*"
            if annotations.get("strikethrough"):
                content = f"~~{content}~~"
            if annotations.get("code"):
                content = f"`{content}`"
            
            if href:
                content = f"[{content}]({href})"
                
            md_text += content
        return md_text

    def convert_page_content(self, page_id):
        """Fetches all blocks of a page and converts them to Markdown string."""
        md_output = ""
        has_more = True
        start_cursor = None
        
        while has_more:
            try:
                response = self.notion.blocks.children.list(
                    block_id=page_id,
                    start_cursor=start_cursor
                )
                blocks = response.get("results", [])
                
                for block in blocks:
                    md_output += self.block_to_markdown(block)
                    
                    if block.get("has_children") and block["type"] not in ["child_page", "child_database", "link_to_page"]:
                         pass

                has_more = response.get("has_more")
                start_cursor = response.get("next_cursor")
                
            except Exception as e:
                print(f"Error converting page content {page_id}: {e}")
                break
                
        return md_output
