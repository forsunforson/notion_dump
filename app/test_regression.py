import unittest
from unittest.mock import MagicMock, patch
import os
import sys
import tempfile
from pathlib import Path

# Set dummy env vars before importing download_notion
os.environ["notion_token"] = "secret_dummy"
os.environ["page_id"] = "dummy_page_id"

# Add app directory to sys.path to ensure imports work
sys.path.append(os.path.join(os.path.dirname(__file__)))

from download_notion import download_page, get_page_metadata

class TestDownloadNotionRegression(unittest.TestCase):
    
    @patch("download_notion.notion")
    @patch("download_notion.converter")
    def test_download_page_yaml_structure(self, mock_converter, mock_notion):
        """
        Regression test to verify that download_page generates correct Markdown 
        with YAML Frontmatter and content.
        """
        # Setup mocks
        page_id = "12345678-1234-1234-1234-1234567890ab"
        
        # Mock page retrieval
        mock_page_obj = {
            "id": page_id,
            "url": "https://notion.so/test-page",
            "created_time": "2023-01-01T10:00:00.000Z",
            "last_edited_time": "2023-01-02T10:00:00.000Z",
            "properties": {
                "title": {
                    "type": "title",
                    "title": [{"plain_text": "Test Page Title"}]
                },
                "Status": {
                    "type": "status",
                    "status": {"name": "Done"}
                },
                "Tags": {
                    "type": "multi_select",
                    "multi_select": [{"name": "Tag1"}, {"name": "Tag2"}]
                }
            }
        }
        
        mock_notion.pages.retrieve.return_value = mock_page_obj
        
        # Mock children list (empty to avoid recursion loop testing here, focusing on file structure)
        mock_notion.blocks.children.list.return_value = {"results": [], "has_more": False}
        
        # Mock converter content
        mock_converter.convert_page_content.return_value = "This is the page content."
        
        # Use a temporary directory for output
        with tempfile.TemporaryDirectory() as tmpdirname:
            output_dir = Path(tmpdirname)
            
            # Execute
            download_page(page_id, output_dir)
            
            # Verify file exists
            expected_filename = f"{page_id}.md"
            file_path = output_dir / expected_filename
            self.assertTrue(file_path.exists())
            
            # Verify content
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                
            # Check YAML Frontmatter
            self.assertIn("---", content)
            self.assertIn(f'id: "{page_id}"', content)
            self.assertIn('title: "Test Page Title"', content)
            self.assertIn('status: "Done"', content)
            self.assertIn('tags:', content)
            self.assertIn('- "Tag1"', content)
            self.assertIn('- "Tag2"', content)
            
            # Check Markdown Content
            self.assertIn("# Test Page Title", content)
            self.assertIn("This is the page content.", content)
            
            # Ensure no old JSON properties
            self.assertNotIn("properties: {", content)

    @patch("download_notion.notion")
    def test_get_page_metadata(self, mock_notion):
        """Verify metadata extraction works with the new structure."""
        page_id = "test_id"
        mock_notion.pages.retrieve.return_value = {
            "id": page_id,
            "created_time": "2023-01-01",
            "last_edited_time": "2023-01-02",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "My Page"}]}
            }
        }
        
        meta = get_page_metadata(page_id)
        self.assertEqual(meta["title"], "My Page")
        self.assertEqual(meta["type"], "page")
        self.assertIsNotNone(meta["page_obj"])

if __name__ == "__main__":
    unittest.main()
