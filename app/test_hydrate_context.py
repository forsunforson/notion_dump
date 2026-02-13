import asyncio
import os
import shutil
import tempfile
from pathlib import Path
import sys

# Add project root to sys.path to ensure we can import app
sys.path.append(os.getcwd())

from observer import ContentObserver

import argparse

# Mock API key to avoid warning
os.environ["AI_API_KEY"] = "test_key"

async def hydrate_file(file_path_str):
    path = Path(file_path_str)
    if not path.exists():
        print(f"Error: File not found at {path}")
        return

    print(f"Hydrating context for: {path}")
    
    # Read file content
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading file: {e}")
        return

    observer = ContentObserver()
    # Use parent dir as root_dir for resolving relative links
    hydrated = await observer._hydrate_context(content, path.parent)
    
    print("\n=== Hydrated Output ===\n")
    print(hydrated)
    print("\n=======================\n")

async def test_hydrate_context():
    print("=== Starting _hydrate_context Test ===")
    
    # 1. Setup temporary test directory
    test_dir = Path("temp_test_hydration")
    if test_dir.exists():
        shutil.rmtree(test_dir)
    test_dir.mkdir()
    print(f"Created temporary directory: {test_dir}")

    try:
        # 2. Create referenced files
        # File 1: Normal short file
        ref1_path = test_dir / "ref1.md"
        with open(ref1_path, "w", encoding="utf-8") as f:
            f.write("This is the content of reference 1.")
        
        # File 2: Long file (to test truncation)
        ref2_path = test_dir / "ref2.md"
        with open(ref2_path, "w", encoding="utf-8") as f:
            # Write 1200 chars
            f.write("A" * 1200)
            
        # File 3-6: To test limit of 5
        for i in range(3, 8):
            with open(test_dir / f"ref{i}.md", "w", encoding="utf-8") as f:
                f.write(f"Content of ref {i}")

        # 3. Prepare content with references
        # Includes:
        # - ref1 (normal)
        # - ref2 (long)
        # - missing_file.md (should be ignored)
        # - ref3, ref4, ref5 (should be included)
        # - ref6 (should be ignored due to limit of 5)
        content = """
# Main Document

Here is a link to [Ref 1](ref1.md).
Here is a link to [Ref 2](ref2.md).
Here is a dead link [Missing](missing_file.md).
Here are more links:
- [Ref 3](ref3.md)
- [Ref 4](ref4.md)
- [Ref 5](ref5.md)
- [Ref 6](ref6.md)
"""
        print("\nInput Content:")
        print(content.strip())

        # 4. Run _hydrate_context
        observer = ContentObserver()
        print("\nRunning _hydrate_context...")
        hydrated_content = await observer._hydrate_context(content, test_dir)

        print("\n=== Output Result ===")
        print(hydrated_content)
        print("=====================\n")

        # 5. Verification
        print("Verifying results...")
        
        # Check structure
        assert "<changed_document>" in hydrated_content
        assert "</changed_document>" in hydrated_content
        assert "<references>" in hydrated_content
        assert "</references>" in hydrated_content
        
        # Check Ref 1 (Normal)
        assert 'title="ref1.md"' in hydrated_content
        assert "This is the content of reference 1." in hydrated_content
        
        # Check Ref 2 (Truncation)
        assert 'title="ref2.md"' in hydrated_content
        # Should have 1000 'A's
        assert "A" * 1000 in hydrated_content
        # Should NOT have 1001 'A's (strict check might depend on how we read/match, but let's check length roughly)
        # The content part for ref2 should be exactly 1000 chars
        import re
        ref2_match = re.search(r'<ref title="ref2.md">\s*(A+)\s*</ref>', hydrated_content)
        if ref2_match:
            print(f"Ref 2 content length: {len(ref2_match.group(1))}")
            assert len(ref2_match.group(1)) == 1000
        else:
            print("Failed to find Ref 2 content block")
            assert False

        # Check Missing File
        assert 'title="missing_file.md"' not in hydrated_content
        
        # Check Limit (Max 5)
        # Included: ref1, ref2, ref3, ref4, ref5
        # Excluded: ref6
        assert 'title="ref3.md"' in hydrated_content
        assert 'title="ref4.md"' in hydrated_content
        assert 'title="ref5.md"' in hydrated_content
        assert 'title="ref6.md"' not in hydrated_content

        print("\n✅ All tests passed successfully!")

    finally:
        # Cleanup
        if test_dir.exists():
            shutil.rmtree(test_dir)
        print(f"Cleaned up temporary directory: {test_dir}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test context hydration")
    parser.add_argument("file", nargs="?", help="Path to markdown file to hydrate")
    args = parser.parse_args()

    if args.file:
        asyncio.run(hydrate_file(args.file))
    else:
        asyncio.run(test_hydrate_context())
