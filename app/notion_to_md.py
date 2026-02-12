from notion_client import Client
from datetime import datetime
import re
import uuid

class NotionToMarkdown:
    def __init__(self, notion_client: Client):
        self.notion = notion_client

    def _format_uuid(self, id_str):
        """Format a Notion ID string into a standard UUID format (with dashes)."""
        try:
            return str(uuid.UUID(id_str))
        except ValueError:
            return id_str

    def _sanitize_filename(self, name):
        """Sanitize the filename to be safe for file systems."""
        # Replace invalid characters with empty string
        name = re.sub(r'[\\/*?:"<>|]', "", name)
        # Replace spaces with underscores
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

    def block_to_markdown(self, block):
        block_type = block["type"]
        
        # Handle supported block types
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
            # Handle external and file images
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

        # child_page handling: convert to markdown link
        elif block_type == "child_page":
            title = block["child_page"]["title"]
            page_id = self._format_uuid(block["id"])
            # For RAG purpose, use ID as filename directly
            # No longer need date prefix or filename sanitization for the link target
            return f"[{title}]({page_id}.md)\n\n"
            
        # child_database handling: ignore content but keep recursion logic in caller
        elif block_type == "child_database":
            return ""

        return "" # Ignore unsupported blocks for now

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
                
                # Pre-process list items to handle nesting (simplified)
                # For now, we just convert sequentially
                
                for block in blocks:
                    md_output += self.block_to_markdown(block)
                    
                    # Handle nested blocks (except child_page/database which are handled externally)
                    if block.get("has_children") and block["type"] not in ["child_page", "child_database"]:
                         # Recursively fetch children for this block
                         # Indent logic would be needed for proper nested lists, skipping for simple implementation
                         pass

                has_more = response.get("has_more")
                start_cursor = response.get("next_cursor")
                
            except Exception as e:
                print(f"Error converting page content {page_id}: {e}")
                break
                
        return md_output
