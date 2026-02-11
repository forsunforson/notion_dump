import os
from dotenv import load_dotenv
from notion_client import Client
from pprint import pprint

load_dotenv()
notion_token = os.getenv("notion_token")
notion = Client(auth=notion_token)
page_id = os.getenv("page_id")

def test_connection():
    try:
        print(f"🚀 正在尝试访问 Notion 页面: {page_id}...")
        
        # 2. 调用 API 获取页面属性
        response = notion.pages.retrieve(page_id=page_id)
        
        print("✅ 成功连通 Notion！")
        print("-" * 20)
        # 打印页面标题（Notion 的 JSON 结构比较深，这样可以抓出标题）
        properties = response.get("properties", {})
        # 通常标题字段名为 'title' 或 'Name'
        title_field = properties.get("title") or properties.get("Name")
        if title_field:
            title = title_field["title"][0]["plain_text"]
            print(f"📄 页面标题为: {title}")
        
    except Exception as e:
        print(f"❌ 出错了: {e}")

if __name__ == "__main__":
    test_connection()
