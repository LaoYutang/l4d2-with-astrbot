import aiohttp
import re
import logging

class WorkshopTools:
    def __init__(self):
        self.api_url = "https://steamworkshopdownloader.io/api/details/file"
        self.headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        self.logger = logging.getLogger("l4d2_plugin.workshop")

    async def process_url(self, url: str):
        """
        处理创意工坊链接，返回解析结果列表
        """
        # 1. Extract ID
        main_id = self._extract_id(url)
        if not main_id:
            return None, "无法从链接中提取 ID"

        # 2. First API call to check details
        # 尝试直接请求 API，看是否返回 children 字段（合集）或 file_url（单品）
        first_data = await self._fetch_details([main_id])
        
        if not first_data:
            # API 失败，尝试 HTML 解析作为 fallback
            return await self._process_via_html_fallback(main_id)

        item_info = first_data[0]
        
        # 检查是否为合集 (包含 children 字段)
        # 用户提示的结构: children: [{"publishedfileid": "...", ...}, ...]
        if "children" in item_info and isinstance(item_info["children"], list) and item_info["children"]:
            child_ids = [str(child.get("publishedfileid")) for child in item_info["children"] if child.get("publishedfileid")]
            if child_ids:
                # 再次请求获取子物品详情
                details = await self._fetch_details(child_ids)
                if details:
                    valid_results = [item for item in details if item.get("result") == 1]
                    return valid_results, "合集"
        
        # 检查是否为单品 (有 file_url)
        if item_info.get("result") == 1 and item_info.get("file_url"):
            return [item_info], "单品"

        # 如果 API 既没返回 children 也没返回 file_url，尝试 HTML 解析
        # 有些合集 API 可能不返回 children
        return await self._process_via_html_fallback(main_id)

    async def _process_via_html_fallback(self, workshop_id: str):
        """
        Fallback: 通过爬取 Steam 网页解析合集
        """
        is_collection, child_ids = await self._resolve_collection_from_html(workshop_id)
        
        if is_collection:
            if not child_ids:
                return None, "检测到合集，但无法提取子物品 ID"
            
            data = await self._fetch_details(child_ids)
            if not data:
                return None, "API 请求失败"
            
            valid_results = [item for item in data if item.get("result") == 1]
            if not valid_results:
                return None, "未找到有效的文件下载信息"
            return valid_results, "合集"
        
        return None, "无法解析该链接 (非合集或 API 无数据)"

    def _extract_id(self, text: str) -> str:
        # Try URL param
        match = re.search(r"[?&]id=(\d+)", text)
        if match:
            return match.group(1)
        # Fallback to numbers if the text is just numbers (though usually it's a URL)
        # But here we expect a URL mostly.
        return None

    async def _resolve_collection_from_html(self, workshop_id: str):
        """
        检查是否为合集，如果是，返回 (True, [id_list])
        否则返回 (False, [])
        """
        steam_url = f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(steam_url, headers={"User-Agent": self.headers["User-Agent"]}, timeout=10) as resp:
                    if resp.status != 200:
                        self.logger.warning(f"Failed to fetch steam page: {resp.status}")
                        return False, []
                    text = await resp.text()
        except Exception as e:
            self.logger.error(f"Error fetching steam page: {repr(e)}")
            return False, []
        
        # Check if collection
        # "Subscribe to all" button usually indicates a collection
        # Or class="subscribeCollection"
        if "subscribeCollection" in text or "Subscribe to all" in text:
            # Extract child IDs
            # Look for the collectionChildren div
            children_block_match = re.search(r'<div class="collectionChildren">(.*?)<div class="cleared">', text, re.DOTALL)
            if children_block_match:
                block = children_block_match.group(1)
                # Extract IDs from links like href="...id=123"
                ids = re.findall(r'id=(\d+)', block)
                # Remove duplicates and ensure unique
                ids = list(set(ids))
                # Remove self ID if present (unlikely in children block but good practice)
                if workshop_id in ids:
                    ids.remove(workshop_id)
                return True, ids
            
            # Fallback: try to find all workshopItem divs if collectionChildren not found
            # This is riskier but might work
            return True, []
        
        return False, []

    async def _fetch_details(self, ids: list):
        # 尝试将 ID 转换为整数，避免 API 因类型问题返回 500
        payload = []
        for i in ids:
            try:
                payload.append(int(i))
            except:
                payload.append(str(i))

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=payload, headers=self.headers, timeout=30) as resp:
                    if resp.status != 200:
                        self.logger.error(f"API returned status {resp.status}")
                        try:
                            err_text = await resp.text()
                            self.logger.error(f"API Error body: {err_text}")
                        except:
                            pass
                        return None
                    return await resp.json()
        except Exception as e:
            self.logger.error(f"Error calling downloader API: {repr(e)}")
            return None
