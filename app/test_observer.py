import asyncio
import os
import argparse
from pathlib import Path
from observer import ContentObserver

async def test_observer(file_path):
    """
    Test the ContentObserver with a local file.
    """
    path = Path(file_path)
    if not path.exists():
        print(f"Error: File not found at {file_path}")
        return

    print(f"Testing Observer on file: {file_path}")
    
    # Ensure API Key is set
    if not os.getenv("AI_API_KEY"):
        print("Error: AI_API_KEY environment variable is not set.")
        print("Please set it in your .env file or export it in your shell.")
        return

    observer = ContentObserver()
    
    try:
        # analyze_changes expects a list of file paths
        await observer.analyze_changes([file_path])
        print("\nTest complete. Check the _reports directory for the result.")
    except Exception as e:
        print(f"Test failed with error: {e}")

def main():
    parser = argparse.ArgumentParser(description="Test ContentObserver with a local file")
    parser.add_argument("file_path", help="Path to the local file to analyze")
    args = parser.parse_args()
    
    # Load environment variables if not already loaded
    from dotenv import load_dotenv
    load_dotenv(override=True)
    
    asyncio.run(test_observer(args.file_path))

if __name__ == "__main__":
    main()
