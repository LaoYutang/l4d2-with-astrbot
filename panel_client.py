"""L4D2 管理面板下载接口客户端。

不依赖 AstrBot，便于独立单元测试。面板接口定义见 l4d2-server：

- ``POST /download/link/parse``：解析工坊 / QQ 闪传链接，返回文件列表
- ``POST /download/add``：创建下载任务（multipart 表单：url / filename / referer）
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Sequence

import aiohttp

PARSE_TIMEOUT_SECONDS = 60
ADD_TIMEOUT_SECONDS = 30
ALL_SELECTION_KEYWORD = "全部"

_NUMBER_SEPARATOR = re.compile(r"[,，\s]+")


class PanelError(Exception):
    """面板接口调用失败，错误消息可直接回复用户。"""


class SelectionError(ValueError):
    """管理员回复的选择内容不合法，错误消息可直接回复用户。"""


class PanelClient:
    """通过面板 HTTP API 解析链接、创建下载任务。"""

    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.token = str(token or "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.token)

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def parse_download_link(self, share_url: str) -> List[Dict[str, Any]]:
        """解析下载链接，返回面板给出的文件条目列表。"""
        data = await self._post_json(
            "/download/link/parse",
            {"url": share_url},
            timeout=PARSE_TIMEOUT_SECONDS,
        )
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise PanelError("面板返回的数据格式异常（缺少文件列表）")
        return [item for item in items if isinstance(item, dict)]

    async def add_download_task(
        self, file_url: str, filename: str = "", referer: str = ""
    ) -> str:
        """创建下载任务，返回面板的文本响应。"""
        form = aiohttp.FormData()
        form.add_field("url", file_url)
        if filename:
            form.add_field("filename", filename)
        if referer:
            form.add_field("referer", referer)

        url = f"{self.base_url}/download/add"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    data=form,
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=ADD_TIMEOUT_SECONDS),
                ) as response:
                    text = await response.text()
                    if response.status != 200:
                        raise PanelError(extract_panel_error(response.status, text))
                    return text.strip() or "下载任务已添加"
        except PanelError:
            raise
        except asyncio.TimeoutError as exc:
            raise PanelError(f"面板请求超时（超过 {ADD_TIMEOUT_SECONDS} 秒）") from exc
        except aiohttp.ClientError as exc:
            raise PanelError(f"连接面板失败：{exc}") from exc

    async def _post_json(self, path: str, payload: Any, timeout: int) -> Any:
        url = f"{self.base_url}{path}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as response:
                    text = await response.text()
                    if response.status != 200:
                        raise PanelError(extract_panel_error(response.status, text))
                    try:
                        return json.loads(text)
                    except ValueError as exc:
                        raise PanelError("面板返回了无法解析的数据") from exc
        except PanelError:
            raise
        except asyncio.TimeoutError as exc:
            raise PanelError(f"面板请求超时（超过 {timeout} 秒）") from exc
        except aiohttp.ClientError as exc:
            raise PanelError(f"连接面板失败：{exc}") from exc


def extract_panel_error(status: int, text: str) -> str:
    """从面板错误响应中提取可读消息。"""
    message = ""
    try:
        data = json.loads(text or "")
    except ValueError:
        data = None
    if isinstance(data, dict):
        for key in ("message", "error"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                message = value.strip()
                break
    if not message:
        message = (text or "").strip()
    if message:
        return f"面板返回错误（HTTP {status}）：{message}"
    return f"面板返回错误（HTTP {status}）"


def is_all_selection(text: str) -> bool:
    """判断回复内容是否为“全部”。"""
    return str(text or "").strip() == ALL_SELECTION_KEYWORD


def parse_number_selection(
    text: str, max_index: int, allow_multiple: bool = True
) -> List[int]:
    """解析数字选择，返回 0 基索引列表（去重、保持输入顺序）。

    仅接受数字与中英文逗号 / 空格分隔；``allow_multiple=False`` 时只允许一个数字。
    失败抛出 ``SelectionError``，错误消息可直接回复用户。
    """
    if max_index <= 0:
        raise SelectionError("没有可选择的项目")
    stripped = str(text or "").strip()
    tokens = [token for token in _NUMBER_SEPARATOR.split(stripped) if token]
    if not tokens or any(not token.isdigit() for token in tokens):
        raise SelectionError("已取消")
    if not allow_multiple and len(tokens) > 1:
        raise SelectionError("已取消")

    numbers = [int(token) for token in tokens]
    if any(number < 1 or number > max_index for number in numbers):
        raise SelectionError(f"序号超出范围（1-{max_index}），已取消")

    indices: List[int] = []
    for number in numbers:
        index = number - 1
        if index not in indices:
            indices.append(index)
    return indices


def filter_supported_items(items: Sequence[Any]) -> List[Dict[str, Any]]:
    """只保留面板标记为支持的条目（.vpk/.zip/.rar/.7z）。"""
    result: List[Dict[str, Any]] = []
    for item in items or []:
        if isinstance(item, dict) and item.get("supported") is True:
            result.append(item)
    return result


def format_file_size(size: Any) -> str:
    """把字节数格式化为可读大小；面板直接给出文本大小时原样返回。"""
    if isinstance(size, str):
        text = size.strip()
        if not text:
            return "未知大小"
        try:
            value = float(text)
        except ValueError:
            return text
    elif isinstance(size, bool) or not isinstance(size, (int, float)):
        return "未知大小"
    else:
        value = float(size)

    if value <= 0:
        return "未知大小"
    for unit, step in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if value >= step:
            return f"{value / step:.2f} {unit}"
    return f"{int(value)} B"


def build_file_list_lines(items: Sequence[Dict[str, Any]]) -> List[str]:
    """生成带编号的文件列表行，供回复消息使用。"""
    lines: List[str] = []
    for index, item in enumerate(items, start=1):
        name = str(item.get("filename") or item.get("title") or f"文件 {index}").strip()
        lines.append(f"{index}. {name}（{format_file_size(item.get('file_size'))}）")
    return lines
