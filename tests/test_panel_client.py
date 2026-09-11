import json
import unittest
from unittest import mock

from panel_client import (
    PanelClient,
    PanelError,
    SelectionError,
    build_file_list_lines,
    extract_panel_error,
    filter_supported_items,
    format_file_size,
    is_all_selection,
    parse_number_selection,
)


class SelectionTests(unittest.TestCase):
    def test_single_selection(self):
        self.assertEqual(parse_number_selection("1", 3, allow_multiple=False), [0])
        self.assertEqual(parse_number_selection(" 3 ", 3, allow_multiple=False), [2])

    def test_multiple_selection_with_separators(self):
        self.assertEqual(parse_number_selection("1,3", 3), [0, 2])
        self.assertEqual(parse_number_selection("1，3", 3), [0, 2])
        self.assertEqual(parse_number_selection("1, 3", 3), [0, 2])
        self.assertEqual(parse_number_selection("2,1,2", 3), [1, 0])

    def test_other_characters_cancel(self):
        for text in ("", "   ", "abc", "取消", "1.a", "全部"):
            with self.assertRaisesRegex(SelectionError, "^已取消$"):
                parse_number_selection(text, 3)

    def test_multiple_rejected_when_single_only(self):
        with self.assertRaisesRegex(SelectionError, "^已取消$"):
            parse_number_selection("1,2", 3, allow_multiple=False)

    def test_out_of_range_cancels(self):
        for text in ("0", "4", "2,5"):
            with self.assertRaisesRegex(SelectionError, "序号超出范围（1-3）"):
                parse_number_selection(text, 3)

    def test_is_all_selection(self):
        self.assertTrue(is_all_selection("全部"))
        self.assertTrue(is_all_selection(" 全部 "))
        self.assertFalse(is_all_selection("全部 1"))
        self.assertFalse(is_all_selection("全"))


class ItemFilterTests(unittest.TestCase):
    def test_filter_supported_items(self):
        items = [
            {"filename": "a.vpk", "supported": True},
            {"filename": "b.txt", "supported": False},
            {"filename": "c.zip", "supported": True},
            {"filename": "d.vpk"},
            "not-a-dict",
            None,
        ]
        self.assertEqual(
            [item["filename"] for item in filter_supported_items(items)],
            ["a.vpk", "c.zip"],
        )

    def test_format_file_size(self):
        self.assertEqual(format_file_size("12345678"), "11.77 MB")
        self.assertEqual(format_file_size(2048), "2.00 KB")
        self.assertEqual(format_file_size(512), "512 B")
        self.assertEqual(format_file_size(3 * 1024**3), "3.00 GB")
        self.assertEqual(format_file_size("12 MB"), "12 MB")
        self.assertEqual(format_file_size(""), "未知大小")
        self.assertEqual(format_file_size(None), "未知大小")
        self.assertEqual(format_file_size(0), "未知大小")
        self.assertEqual(format_file_size(-1), "未知大小")
        self.assertEqual(format_file_size(True), "未知大小")
        self.assertEqual(format_file_size(["x"]), "未知大小")

    def test_build_file_list_lines(self):
        items = [
            {"filename": "a.vpk", "file_size": "2048"},
            {"title": "只是标题", "file_size": "12 MB"},
            {"filename": ""},
        ]
        self.assertEqual(
            build_file_list_lines(items),
            ["1. a.vpk（2.00 KB）", "2. 只是标题（12 MB）", "3. 文件 3（未知大小）"],
        )


class PanelErrorTests(unittest.TestCase):
    def test_extract_panel_error_prefers_json_message(self):
        message = extract_panel_error(
            507, '{"error":"insufficient_storage","message":"磁盘空间不足，当前使用率超过90%"}'
        )
        self.assertEqual(message, "面板返回错误（HTTP 507）：磁盘空间不足，当前使用率超过90%")

    def test_extract_panel_error_falls_back_to_error_field(self):
        message = extract_panel_error(403, '{"error":"access_denied"}')
        self.assertEqual(message, "面板返回错误（HTTP 403）：access_denied")

    def test_extract_panel_error_falls_back_to_text(self):
        self.assertEqual(
            extract_panel_error(401, "密码错误或令牌已失效"),
            "面板返回错误（HTTP 401）：密码错误或令牌已失效",
        )
        self.assertEqual(extract_panel_error(500, ""), "面板返回错误（HTTP 500）")

    def test_client_configured_and_base_url(self):
        client = PanelClient("http://127.0.0.1:27020/", " token ")
        self.assertTrue(client.configured)
        self.assertEqual(client.base_url, "http://127.0.0.1:27020")
        self.assertEqual(client.token, "token")
        self.assertFalse(PanelClient("", "token").configured)
        self.assertFalse(PanelClient("http://127.0.0.1:27020", "").configured)


class _FakeResponse:
    def __init__(self, status, text):
        self.status = status
        self._text = text

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class _FakeSession:
    def __init__(self, response):
        self._response = response
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return self._response


def _form_field_map(form_data):
    """从 aiohttp.FormData 中提取字段，兼容不同版本的内部结构。"""
    fields = {}
    for entry in form_data._fields:
        headers = entry[0]
        value = entry[-1] if len(entry) >= 3 else entry[1].get("value", "")
        name = headers.get("name") if hasattr(headers, "get") else None
        if name is not None:
            fields[name] = value
    return fields


class PanelClientRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_parse_download_link_returns_items(self):
        payload = {
            "source_type": "qq_flash_transfer",
            "source_id": "abc",
            "items": [{"filename": "a.vpk", "supported": True}],
        }
        session = _FakeSession(_FakeResponse(200, json.dumps(payload)))
        with mock.patch("panel_client.aiohttp.ClientSession", return_value=session):
            client = PanelClient("http://127.0.0.1:27020", "secret")
            items = await client.parse_download_link("https://qfile.qq.com/q/abc")

        self.assertEqual(len(items), 1)
        url, kwargs = session.requests[0]
        self.assertEqual(url, "http://127.0.0.1:27020/download/link/parse")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(kwargs["json"], {"url": "https://qfile.qq.com/q/abc"})

    async def test_parse_download_link_rejects_missing_items(self):
        session = _FakeSession(_FakeResponse(200, '{"source_type":"workshop"}'))
        with mock.patch("panel_client.aiohttp.ClientSession", return_value=session):
            client = PanelClient("http://127.0.0.1:27020", "secret")
            with self.assertRaisesRegex(PanelError, "数据格式异常"):
                await client.parse_download_link("https://qfile.qq.com/q/abc")

    async def test_parse_download_link_maps_http_error(self):
        session = _FakeSession(_FakeResponse(401, "密码错误或令牌已失效"))
        with mock.patch("panel_client.aiohttp.ClientSession", return_value=session):
            client = PanelClient("http://127.0.0.1:27020", "bad")
            with self.assertRaisesRegex(PanelError, "密码错误或令牌已失效"):
                await client.parse_download_link("https://qfile.qq.com/q/abc")

    async def test_add_download_task_posts_form(self):
        session = _FakeSession(_FakeResponse(200, "下载任务已添加"))
        with mock.patch("panel_client.aiohttp.ClientSession", return_value=session):
            client = PanelClient("http://127.0.0.1:27020", "secret")
            result = await client.add_download_task(
                "https://example.com/a.vpk?filename=a.vpk", "a.vpk", "https://qfile.qq.com/q/abc"
            )

        self.assertEqual(result, "下载任务已添加")
        url, kwargs = session.requests[0]
        self.assertEqual(url, "http://127.0.0.1:27020/download/add")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(
            _form_field_map(kwargs["data"]),
            {
                "url": "https://example.com/a.vpk?filename=a.vpk",
                "filename": "a.vpk",
                "referer": "https://qfile.qq.com/q/abc",
            },
        )


if __name__ == "__main__":
    unittest.main()
