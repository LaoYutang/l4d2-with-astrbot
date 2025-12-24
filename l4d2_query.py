import a2s
import socket
from typing import Dict, Any, List, Optional, Tuple

class L4D2Server:
    def __init__(self, name: str, address: str):
        self.name = name
        self.address = address
        self.ip, self.port = self._parse_address(address)

    def _parse_address(self, address: str) -> Tuple[str, int]:
        if ":" in address:
            parts = address.split(":")
            return parts[0], int(parts[1])
        return address, 27015

    def query_info(self) -> Optional[Dict[str, Any]]:
        """查询服务器基本信息"""
        try:
            # timeout 设置为 2 秒，避免阻塞太久
            info = a2s.info((self.ip, self.port), timeout=2.0)
            return {
                "server_name": info.server_name,
                "map_name": info.map_name,
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
