import a2s
import socket
import urllib.request
from typing import Dict, Any, List, Optional, Tuple
from astrbot.api.all import logger

class L4D2Server:
    def __init__(self, name: str, address: str, map_name_url: str = ""):
        self.name = name
        self.address = address
        self.map_name_url = map_name_url
        self.ip, self.port = self._parse_address(address)

    def _parse_address(self, address: str) -> Tuple[str, int]:
        if ":" in address:
            parts = address.split(":")
            return parts[0], int(parts[1])
        return address, 27015

    def _get_map_real_name(self, map_code: str) -> str:
        if not self.map_name_url:
            return map_code
            
        # 确保 URL 末尾没有 /，然后拼接
        base_url = self.map_name_url.rstrip('/')
        url = f"{base_url}/{map_code}"
        logger.info(f"URL: {url}")

        try:
            with urllib.request.urlopen(url, timeout=2.0) as response:
                if response.status == 200:
                    content = response.read().decode('utf-8').strip()
                    if content:
                        logger.info(f"Result: {content}")
                        return content
        except Exception as e:
            logger.error(f"Error getting map name: {e}")
            pass
        return map_code

    def query_info(self) -> Optional[Dict[str, Any]]:
        """查询服务器基本信息"""
        try:
            # timeout 设置为 2 秒，避免阻塞太久
            info = a2s.info((self.ip, self.port), timeout=2.0)
            
            # 获取地图真实名称
            real_map_name = self._get_map_real_name(info.map_name)

            return {
                "server_name": info.server_name,
                "map_name": real_map_name,
                "player_count": info.player_count,
                "max_players": info.max_players,
                "ping": int(info.ping * 1000)
            }
        except Exception as e:
            # 捕获所有异常以防止崩溃，返回 None 表示离线或无法连接
            return None

    def query_players(self) -> Optional[List[Dict[str, Any]]]:
        """查询玩家列表"""
        try:
            players = a2s.players((self.ip, self.port), timeout=2.0)
            # 过滤掉名字为空的玩家（有时是连接中的玩家或机器人）
            return [{"name": p.name, "score": p.score, "duration": p.duration} for p in players if p.name]
        except Exception as e:
            return None

    def execute_rcon(self, password: str, command: str) -> str:
        """通过 RCON 执行指令"""
        from .rcon_client import RCONClient
        client = RCONClient(self.ip, self.port, password)
        return client.execute(command)

    def restart(self, password: str) -> str:
        """通过 RCON 重启服务器 (发送 _restart 指令)"""
        return self.execute_rcon(password, "_restart")
