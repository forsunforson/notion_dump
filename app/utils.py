import yaml
import re
from datetime import datetime

class ForceDoubleQuoteStr(str):
    pass

class NotionMapper:
    @staticmethod
    def to_snake_case(text):
        """Convert text to snake_case."""
        if not text:
            return ""
        # Replace non-alphanumeric characters (except underscores) with spaces
        s = re.sub(r'[^a-zA-Z0-9_]', ' ', text)
        # Convert to lowercase and strip whitespace
        s = s.strip().lower()
        # Replace spaces with underscores
        s = re.sub(r'\s+', '_', s)
        return s

    @staticmethod
    def _convert_date(date_str):
        """Convert Notion date string to ISO 8601 format."""
        if not date_str:
            return None
        try:
            # Notion dates are usually ISO 8601 already, but we ensure consistency
            # If it's just a date (YYYY-MM-DD), keep it as is or add time?
            # User requested "YYYY-MM-DDTHH:mm:ssZ"
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
        
        # System Fields
        data["id"] = NotionMapper._wrap_value(page.get("id"))
        data["url"] = NotionMapper._wrap_value(page.get("url"))
        data["created_time"] = NotionMapper._wrap_value(NotionMapper._convert_date(page.get("created_time")))
        data["last_edited_time"] = NotionMapper._wrap_value(NotionMapper._convert_date(page.get("last_edited_time")))
        
        # Extract properties
        properties = page.get("properties", {})
        
        # Handle Title specifically
        title = "Untitled"
        for key, prop in properties.items():
            if prop.get("type") == "title":
                title = NotionMapper.map_property(prop)
                break
        
        data["title"] = NotionMapper._wrap_value(title)

        # Process other properties
        for key, prop in properties.items():
            prop_type = prop.get("type")
            if prop_type == "title":
                continue 
            
            # Skip duplicated time fields that are already in system fields
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
