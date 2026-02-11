from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()
# 指向你下载的文件
SERVICE_ACCOUNT_FILE = 'service_account.json'
SCOPES = ['https://www.googleapis.com/auth/drive.metadata.readonly']

creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)

service = build('drive', 'v3', credentials=creds)

# 列出你能看到的文件夹，验证权限是否共享成功
results = service.files().list(
    pageSize=10, fields="nextPageToken, files(id, name)").execute()
items = results.get('files', [])
FOLDER_ID = os.getenv('folder_id')
try:
    folder = service.files().get(fileId=FOLDER_ID, fields='id, name').execute()
    print(f"✅ 成功连接！服务账号可以识别文件夹: {folder['name']}")
except Exception as e:
    print(f"❌ 依然无法访问。错误原因: {e}")
