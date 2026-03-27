import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

import download


class DownloadConfigTests(unittest.TestCase):
    def test_resolve_token_prefers_cli_token(self):
        token = download.resolve_token(
            cli_token="cli-token",
            env={"TELEGRAM_BOT_TOKEN": "env-token"},
        )
        self.assertEqual(token, "cli-token")

    def test_resolve_token_uses_env_token(self):
        token = download.resolve_token(
            cli_token=None,
            env={"TELEGRAM_BOT_TOKEN": "env-token"},
        )
        self.assertEqual(token, "env-token")

    def test_resolve_token_raises_when_missing(self):
        with self.assertRaises(RuntimeError) as ctx:
            download.resolve_token(cli_token=None, env={})
        self.assertIn("--token", str(ctx.exception))
        self.assertIn("TELEGRAM_BOT_TOKEN", str(ctx.exception))

    def test_main_uses_cli_token_for_api_and_file_urls(self):
        with (
            patch(
                "download.api_get", return_value={"file_path": "path/file.bin"}
            ) as api_get,
            patch("download.download_file") as download_file,
        ):
            download.main(["--token", "cli-token", "file-id", "out.bin"], env={})

        self.assertEqual(api_get.call_count, 1)
        self.assertIn("cli-token", api_get.call_args.kwargs["api_base"])
        self.assertEqual(download_file.call_count, 1)
        self.assertIn("cli-token", download_file.call_args.kwargs["file_base"])

    def test_main_uses_env_token_when_cli_not_provided(self):
        with (
            patch(
                "download.api_get", return_value={"file_path": "path/file.bin"}
            ) as api_get,
            patch("download.download_file") as download_file,
        ):
            download.main(
                ["file-id", "out.bin"], env={"TELEGRAM_BOT_TOKEN": "env-token"}
            )

        self.assertEqual(api_get.call_count, 1)
        self.assertIn("env-token", api_get.call_args.kwargs["api_base"])
        self.assertEqual(download_file.call_count, 1)
        self.assertIn("env-token", download_file.call_args.kwargs["file_base"])

    def test_download_file_allows_output_without_parent_directory(self):
        with TemporaryDirectory() as temp_dir:
            source_path = f"{temp_dir}/source.bin"
            with open(source_path, "wb") as source_file:
                source_file.write(b"payload")

            with patch(
                "download.urllib.request.urlopen", return_value=open(source_path, "rb")
            ):
                output_path = f"{temp_dir}/out.bin"
                download.download_file(
                    "remote/file.bin",
                    output_path,
                    file_base="https://example.test/file",
                )

            with open(output_path, "rb") as output_file:
                self.assertEqual(output_file.read(), b"payload")
