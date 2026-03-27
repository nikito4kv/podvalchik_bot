import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
import shutil


def build_api_urls(token):
    return (
        f"https://api.telegram.org/bot{token}",
        f"https://api.telegram.org/file/bot{token}",
    )


def resolve_token(cli_token=None, env=None):
    if cli_token:
        return cli_token
    env_vars = os.environ if env is None else env
    env_token = env_vars.get("TELEGRAM_BOT_TOKEN")
    if env_token:
        return env_token
    raise RuntimeError(
        "Telegram bot token is required. Pass --token or set TELEGRAM_BOT_TOKEN."
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Download a Telegram file by file_id.")
    parser.add_argument("file_id")
    parser.add_argument("output_path")
    parser.add_argument(
        "--token",
        help="Telegram bot token. If omitted, TELEGRAM_BOT_TOKEN is used.",
    )
    return parser.parse_args(argv)


def api_get(method, params, api_base):
    query = urllib.parse.urlencode(params)
    url = f"{api_base}/{method}?{query}"
    with urllib.request.urlopen(url) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error: {data}")
    return data["result"]


def download_file(file_path, output_path, file_base):
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    url = f"{file_base}/{file_path}"
    tmp_path = output_path + ".tmp"
    with urllib.request.urlopen(url) as resp, open(tmp_path, "wb") as f:
        shutil.copyfileobj(resp, f)
    os.replace(tmp_path, output_path)


def main(argv=None, env=None):
    args = parse_args(argv)
    token = resolve_token(cli_token=args.token, env=env)
    api_base, file_base = build_api_urls(token)

    info = api_get("getFile", {"file_id": args.file_id}, api_base=api_base)
    file_path = info.get("file_path")
    if not file_path:
        raise RuntimeError(f"No file_path in response: {info}")

    download_file(file_path, args.output_path, file_base=file_base)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except Exception as exc:
        sys.stderr.write(str(exc) + "\n")
        sys.exit(1)
