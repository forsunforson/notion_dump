import unittest
from utils import NotionMapper

class TestNotionMapper(unittest.TestCase):
    def test_special_char_title(self):
        # TC-01
        page = {
            "id": "123",
            "url": "http://example.com",
            "created_time": "2023-01-01T10:00:00.000Z",
            "last_edited_time": "2023-01-02T10:00:00.000Z",
            "properties": {
                "Name": {
                    "type": "title",
                    "title": [{"plain_text": 'Bug fix: "NullPointer" error'}]
                }
            }
        }
        data = NotionMapper.page_to_dict(page)
        yaml_str = NotionMapper.to_yaml(data)
        
        self.assertIn('title: "Bug fix: \\"NullPointer\\" error"', yaml_str)
        # Verify it parses back correctly
        import yaml
        parsed = yaml.safe_load(yaml_str.replace('---', ''))
        self.assertEqual(parsed['title'], 'Bug fix: "NullPointer" error')

    def test_multi_tags(self):
        # TC-02
        page = {
            "id": "123",
            "properties": {
                "Tags": {
                    "type": "multi_select",
                    "multi_select": [{"name": "AI"}, {"name": "RAG"}]
                }
            }
        }
        data = NotionMapper.page_to_dict(page)
        # Note: data['tags'] elements are ForceDoubleQuoteStr, which inherit from str, so equality works
        self.assertEqual(data['tags'], ["AI", "RAG"])
        yaml_str = NotionMapper.to_yaml(data)
        self.assertIn('- "AI"', yaml_str)
        self.assertIn('- "RAG"', yaml_str)

    def test_empty_properties(self):
        # TC-03
        page = {
            "id": "123",
            "properties": {
                "Empty Tags": {
                    "type": "multi_select",
                    "multi_select": []
                },
                "Empty Status": {
                    "type": "status",
                    "status": None
                }
            }
        }
        data = NotionMapper.page_to_dict(page)
        self.assertNotIn('empty_tags', data)
        self.assertNotIn('empty_status', data)

    def test_date_format(self):
        # TC-04
        page = {
            "id": "123",
            "created_time": "2026-02-12T10:00:00.000Z",
            "properties": {}
        }
        data = NotionMapper.page_to_dict(page)
        self.assertEqual(data['created_time'], "2026-02-12T10:00:00Z")

if __name__ == '__main__':
    unittest.main()
