import unittest
from app.utils.plain import to_plain
from app.utils.notion_meta import extract_title, get_page_meta
from app.utils.text_chunking import split_text_smart, split_text_by_length
from app.utils.notion_ids import normalize_uuid
from app.utils.frontmatter import parse_frontmatter


class TestRefactoredUtils(unittest.TestCase):
    
    def test_to_plain(self):
        # Test basic types
        self.assertEqual(to_plain(1), 1)
        self.assertEqual(to_plain("s"), "s")
        self.assertEqual(to_plain([1, 2]), [1, 2])
        self.assertEqual(to_plain({"a": 1}), {"a": 1})
        
        # Test nested structures
        data = {"a": [1, {"b": 2}]}
        self.assertEqual(to_plain(data), data)

    def test_normalize_uuid(self):
        # Test valid UUID
        u = "12345678-1234-1234-1234-1234567890ab"
        self.assertEqual(normalize_uuid(u), u)
        
        # Test compact UUID
        compact = "123456781234123412341234567890ab"
        self.assertEqual(normalize_uuid(compact), u)
        
        # Test invalid
        self.assertEqual(normalize_uuid("invalid"), "invalid")
        self.assertIsNone(normalize_uuid(None))

    def test_extract_title(self):
        # Test page
        page = {
            "object": "page",
            "properties": {
                "Name": {
                    "type": "title",
                    "title": [{"plain_text": "My Page"}]
                }
            }
        }
        self.assertEqual(extract_title(page), "My Page")
        
        # Test database
        db = {
            "object": "database",
            "title": [{"plain_text": "My Database"}]
        }
        self.assertEqual(extract_title(db), "My Database")

    def test_split_text_smart(self):
        # Test simple split
        text = "a" * 100
        chunks = split_text_smart(text, max_chars=50)
        self.assertEqual(len(chunks), 2)
        
        # Test paragraph split
        para1 = "a" * 40
        para2 = "b" * 40
        text = f"{para1}\n\n{para2}"
        chunks = split_text_smart(text, max_chars=50)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0], para1)
        self.assertEqual(chunks[1], para2)

    def test_parse_frontmatter(self):
        content = "---\ntitle: Test\n---\nBody content"
        fm, body = parse_frontmatter(content)
        self.assertEqual(fm.get("title"), "Test")
        self.assertEqual(body.strip(), "Body content")

if __name__ == "__main__":
    unittest.main()
