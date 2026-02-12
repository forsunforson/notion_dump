import os
import json
from dotenv import load_dotenv
from notion_client import Client

# Load environment variables
load_dotenv()

# Configuration
NOTION_TOKEN = os.getenv("notion_token")
PAGE_ID = os.getenv("page_id")

if not NOTION_TOKEN or not PAGE_ID:
    print("Please set notion_token and page_id in .env file")
    exit(1)

# Initialize client
notion = Client(auth=NOTION_TOKEN)

def inspect_page_blocks(page_id):
    print(f"Fetching blocks for page: {page_id}...")
    try:
        # Fetch the first 50 blocks
        response = notion.blocks.children.list(block_id=page_id, page_size=50)
        blocks = response.get("results", [])
        
        print(f"Retrieved {len(blocks)} blocks.")
        
        # Save to a JSON file for easy inspection
        output_file = "notion_blocks_dump.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(blocks, f, indent=2, ensure_ascii=False)
            
        print(f"Blocks dumped to {output_file}")
        
        # Look for child_database
        for block in blocks:
            if block["type"] == "child_database":
                print("\n--- Found Child Database ---")
                print(json.dumps(block, indent=2, ensure_ascii=False))
                
                db_id = block["id"]
                print(f"\nAttempting to retrieve database details for ID: {db_id}")
                try:
                    db_info = notion.databases.retrieve(database_id=db_id)
                    print("Database Retrieve Success!")
                    print(json.dumps(db_info, indent=2, ensure_ascii=False))
                    
                    print(f"\nAttempting to query database: {db_id}")
                    # Try using the helper method if it exists, or raw request
                    if hasattr(notion.databases, 'query'):
                        print("Using notion.databases.query...")
                        query_result = notion.databases.query(database_id=db_id, page_size=1)
                    else:
                        print("Using notion.request (fallback)...")
                        query_result = notion.request(
                            path=f"databases/{db_id}/query",
                            method="POST",
                            body={"page_size": 1}
                        )
                        
                    print("Database Query Success!")
                    print(json.dumps(query_result, indent=2, ensure_ascii=False))
                    
                except Exception as e:
                    # Check for Invalid request URL and try data_sources fallback
                    if "Invalid request URL" in str(e) and hasattr(notion, "data_sources"):
                        print(f"Standard query failed ({e}), attempting data_sources.query...")
                        try:
                            # Try with data_source_id (which might be the db_id itself or we need to resolve it)
                            # For inspect script, let's first check if we have data_sources in retrieved info
                            source_id = db_id
                            if "data_sources" in db_info and db_info["data_sources"]:
                                source_id = db_info["data_sources"][0]["id"]
                                print(f"Resolved Linked Database Source ID: {source_id}")
                            
                            query_result = notion.data_sources.query(data_source_id=source_id, page_size=1)
                            print("Data Sources Query Success!")
                            print(json.dumps(query_result, indent=2, ensure_ascii=False))
                        except Exception as inner_e:
                            print(f"Fallback to data_sources.query also failed: {inner_e}")
                            import traceback
                            traceback.print_exc()
                    else:
                        print(f"Error interacting with database: {e}")
                        import traceback
                        traceback.print_exc()
                
                # Stop after first database to avoid log spam
                break

    except Exception as e:
        print(f"Error fetching blocks: {e}")

if __name__ == "__main__":
    inspect_page_blocks(PAGE_ID)
