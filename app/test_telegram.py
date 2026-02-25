import asyncio
import os
import argparse
from dotenv import load_dotenv
from services.telegram_service import TelegramService

load_dotenv(override=True)


async def test_config():
    """
    Test if Telegram is properly configured.
    """
    print("=" * 50)
    print("Testing Telegram Configuration")
    print("=" * 50)
    
    service = TelegramService()
    
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    print(f"\nTELEGRAM_BOT_TOKEN: {'✓ Set' if bot_token else '✗ Not set'}")
    print(f"TELEGRAM_CHAT_ID: {'✓ Set' if chat_id else '✗ Not set'}")
    print(f"\nis_configured: {service.is_configured}")
    
    if service.is_configured:
        print("\n✅ Telegram is properly configured!")
    else:
        print("\n❌ Telegram is NOT configured. Please set environment variables.")
    
    return service.is_configured


async def test_send_message(text: str = None, parse_mode: str = "Markdown"):
    """
    Test sending a message via Telegram.
    """
    print("=" * 50)
    print("Testing Send Message")
    print("=" * 50)
    
    service = TelegramService()
    
    if not service.is_configured:
        print("\n❌ Telegram not configured. Run 'test config' first.")
        return False
    
    if text is None:
        text = "*Test Message*\n\nThis is a test message from notion_dump CLI."
    
    print(f"\nSending message...")
    print(f"Parse mode: {parse_mode}")
    print(f"Text preview: {text[:100]}{'...' if len(text) > 100 else ''}")
    
    success = await service.send_message(text, parse_mode)
    
    if success:
        print("\n✅ Message sent successfully!")
    else:
        print("\n❌ Failed to send message. Check logs for details.")
    
    return success


async def test_send_long_message():
    """
    Test sending a long message to verify handling.
    """
    print("=" * 50)
    print("Testing Long Message")
    print("=" * 50)
    
    long_text = "*Long Message Test*\n\n" + "This is a test line.\n" * 100
    long_text += f"\n\nTotal characters: {len(long_text)}"
    
    print(f"\nMessage length: {len(long_text)} characters")
    
    return await test_send_message(long_text)


async def test_send_markdown():
    """
    Test sending a message with Markdown formatting.
    """
    print("=" * 50)
    print("Testing Markdown Formatting")
    print("=" * 50)
    
    markdown_text = """
*Bold text*
_Italic text_
`Inline code`
```
Code block
with multiple lines
```
[Link text](https://example.com)

- Item 1
- Item 2
- Item 3
"""
    
    return await test_send_message(markdown_text.strip(), "Markdown")


async def test_send_html():
    """
    Test sending a message with HTML formatting.
    """
    print("=" * 50)
    print("Testing HTML Formatting")
    print("=" * 50)
    
    html_text = """
<b>Bold text</b>
<i>Italic text</i>
<code>Inline code</code>
<pre>
Code block
with multiple lines
</pre>
<a href="https://example.com">Link text</a>

• Item 1
• Item 2
• Item 3
"""
    
    return await test_send_message(html_text.strip(), "HTML")


async def interactive_mode():
    """
    Interactive mode for sending custom messages.
    """
    print("=" * 50)
    print("Interactive Mode")
    print("=" * 50)
    print("\nEnter your message (press Enter twice to send, or type 'quit' to exit):")
    
    service = TelegramService()
    
    if not service.is_configured:
        print("\n❌ Telegram not configured. Run 'test config' first.")
        return
    
    while True:
        lines = []
        empty_line_count = 0
        
        while True:
            try:
                line = input()
                if line == "quit":
                    print("\nExiting interactive mode...")
                    return
                if line == "":
                    empty_line_count += 1
                    if empty_line_count >= 2:
                        break
                else:
                    empty_line_count = 0
                lines.append(line)
            except EOFError:
                break
        
        text = "\n".join(lines).strip()
        if not text:
            continue
        
        print("\nChoose parse mode:")
        print("1. Markdown (default)")
        print("2. HTML")
        print("3. None")
        
        choice = input("Enter choice (1-3): ").strip()
        
        parse_mode = "Markdown"
        if choice == "2":
            parse_mode = "HTML"
        elif choice == "3":
            parse_mode = None
        
        success = await service.send_message(text, parse_mode)
        
        if success:
            print("\n✅ Message sent!")
        else:
            print("\n❌ Failed to send message.")
        
        print("\nEnter another message (or 'quit' to exit):")


def main():
    parser = argparse.ArgumentParser(
        description="Test TelegramService functionality",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python app/test_telegram.py config              # Check configuration
  python app/test_telegram.py send                # Send test message
  python app/test_telegram.py send "Hello World"  # Send custom message
  python app/test_telegram.py markdown            # Test Markdown formatting
  python app/test_telegram.py html                # Test HTML formatting
  python app/test_telegram.py long                # Test long message
  python app/test_telegram.py interactive         # Interactive mode
        """
    )
    
    parser.add_argument(
        "command",
        choices=["config", "send", "markdown", "html", "long", "interactive"],
        help="Test command to run"
    )
    parser.add_argument(
        "text",
        nargs="?",
        help="Custom text to send (for 'send' command)"
    )
    parser.add_argument(
        "--parse-mode",
        choices=["Markdown", "HTML"],
        default="Markdown",
        help="Parse mode for message (default: Markdown)"
    )
    
    args = parser.parse_args()
    
    if args.command == "config":
        asyncio.run(test_config())
    elif args.command == "send":
        asyncio.run(test_send_message(args.text, args.parse_mode))
    elif args.command == "markdown":
        asyncio.run(test_send_markdown())
    elif args.command == "html":
        asyncio.run(test_send_html())
    elif args.command == "long":
        asyncio.run(test_send_long_message())
    elif args.command == "interactive":
        asyncio.run(interactive_mode())


if __name__ == "__main__":
    main()
