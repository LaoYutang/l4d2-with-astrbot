import time
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from astrbot.api.all import logger


class HeyboxVoiceClient:
    """Client for Heybox voice room APIs."""

    CHANNEL_USERS_URL = "https://chat.xiaoheihe.cn/chatroom/v2/channel/user/list"
    ROOM_USERS_URL = "https://chat.xiaoheihe.cn/chatroom/v2/room/users"
    COMMON_PARAMS = {
        "client_type": "heybox_chat",
        "x_client_type": "web",
        "os_type": "web",
        "x_os_type": "bot",
        "x_app": "heybox_chat",
        "chat_os_type": "bot",
        "chat_version": "1.30.0",
    }
    ROOM_USERS_CACHE_TTL = 600
    ROOM_USERS_PAGE_LIMIT = 100

    def __init__(self, bot_id: str = "", token: str = "", timeout: float = 5.0):
        self.bot_id = str(bot_id or "").strip()
        self.token = str(token or "").strip()
        self.timeout = timeout
        self._room_user_cache: Dict[str, Tuple[float, Dict[str, str]]] = {}

    def enabled(self) -> bool:
        return bool(self.bot_id and self.token)

    async def get_channel_user_ids(self, room_id: str, channel_id: str) -> Optional[List[str]]:
        if not self.enabled() or not room_id or not channel_id:
            return None

        params = {
            **self.COMMON_PARAMS,
            "channel_id": str(channel_id),
            "room_id": str(room_id),
            "heybox_id": self.bot_id,
        }
        data = await self._get_json(self.CHANNEL_USERS_URL, params)
        if not data or data.get("status") != "ok":
            return None

        result = data.get("result") or {}
        user_ids = result.get("user_ids")
        if user_ids is None:
            return []
        if isinstance(user_ids, list):
            return [str(user_id) for user_id in user_ids]

        logger.warning(f"[HeyboxVoice] Unexpected user_ids type: {type(user_ids).__name__}")
        return None

    async def get_channel_user_names(self, room_id: str, channel_id: str) -> Optional[List[str]]:
        user_ids = await self.get_channel_user_ids(room_id, channel_id)
        if user_ids is None:
            return None
        if not user_ids:
            return []

        user_map = await self.get_room_user_map(room_id)
        if user_map is None:
            return None

        return [user_map.get(user_id, user_id) for user_id in user_ids]

    async def get_room_user_map(self, room_id: str) -> Optional[Dict[str, str]]:
        if not self.enabled() or not room_id:
            return None

        room_id = str(room_id)
        now = time.time()
        cached = self._room_user_cache.get(room_id)
        if cached:
            timestamp, user_map = cached
            if now - timestamp < self.ROOM_USERS_CACHE_TTL:
                return user_map

        user_map: Dict[str, str] = {}
        offset = 0
        total_count: Optional[int] = None

        while True:
            params = {
                **self.COMMON_PARAMS,
                "heybox_id": self.bot_id,
                "offset": offset,
                "limit": self.ROOM_USERS_PAGE_LIMIT,
                "room_id": room_id,
            }
            data = await self._get_json(self.ROOM_USERS_URL, params)
            if not data or data.get("status") != "ok":
                return None

            room_info = (data.get("result") or {}).get("room_info") or {}
            users = room_info.get("user_info") or []
            if not isinstance(users, list):
                logger.warning(f"[HeyboxVoice] Unexpected user_info type: {type(users).__name__}")
                return None

            if total_count is None:
                total_count = self._safe_int(room_info.get("user_count"))

            for user in users:
                if not isinstance(user, dict):
                    continue
                user_id = user.get("user_id")
                if user_id is None:
                    continue
                display_name = self._get_display_name(user)
                user_map[str(user_id)] = display_name or str(user_id)

            offset += len(users)
            if len(users) < self.ROOM_USERS_PAGE_LIMIT:
                break
            if total_count is not None and offset >= total_count:
                break

        self._room_user_cache[room_id] = (now, user_map)
        return user_map

    async def _get_json(self, url: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        headers = {"token": self.token}
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status != 200:
                        logger.warning(f"[HeyboxVoice] HTTP {response.status} for {url}")
                        return None
                    return await response.json(content_type=None)
        except Exception as e:
            logger.warning(f"[HeyboxVoice] Request failed for {url}: {type(e).__name__} - {e}")
            return None

    def _get_display_name(self, user: Dict[str, Any]) -> str:
        nickname = str(user.get("nickname") or "").strip()
        if nickname:
            return nickname
        username = str(user.get("username") or "").strip()
        return username

    def _safe_int(self, value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
