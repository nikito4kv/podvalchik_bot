import json
import os
import sys
import urllib.parse
import urllib.request
import shutil

TOKEN = "8573008430:AAHfBOzv67ukoc2-9xVkCaRZclucOMohnG4"

API_BASE = f"https://api.telegram.org/bot{TOKEN}"
FILE_BASE = f"https://api.telegram.org/file/bot{TOKEN}"

def api_get(method, params):
    query = urllib.parse.urlencode(params)
    url = f"{API_BASE}/{method}?{query}"
    with urllib.request.urlopen(url) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error: {data}")
    return data["result"]

def download_file(file_path, output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    url = f"{FILE_BASE}/{file_path}"
    tmp_path = output_path + ".tmp"
    with urllib.request.urlopen(url) as resp, open(tmp_path, "wb") as f:
        shutil.copyfileobj(resp, f)
    os.replace(tmp_path, output_path)

def main():
    if len(sys.argv) != 3:
        sys.stderr.write("Usage: download.py <file_id> <output_path>\n")
        sys.exit(2)

    file_id = sys.argv[1]
    output_path = sys.argv[2]

    info = api_get("getFile", {"file_id": file_id})
    file_path = info.get("file_path")
    if not file_path:
        raise RuntimeError(f"No file_path in response: {info}")

    download_file(file_path, output_path)

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        sys.stderr.write(str(exc) + "\n")
        sys.exit(1)