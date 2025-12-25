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

    def restart(self, password: str) -> str:
        """通过 RCON 重启服务器 (发送 restart 指令)"""
        import valve.rcon
        import socket
        
        rcon = valve.rcon.RCON((self.ip, self.port), password, timeout=5)
        
        # 1. 尝试建立连接和认证
        try:
            rcon.connect()
            rcon.authenticate()
        except (socket.timeout, TimeoutError, ConnectionRefusedError, OSError) as e:
            return f"连接失败: 无法连接到服务器 ({type(e).__name__})。请检查服务器是否在线。"
        except valve.rcon.RCONAuthenticationError:
            return "RCON 认证失败：密码错误。"
        except Exception as e:
            return f"连接异常: {type(e).__name__} - {e}"

        # 2. 连接成功，尝试发送指令
        try:
            # 发送 _restart 指令 (通常用于彻底重启服务器进程)
            response = rcon.execute("_restart")
            
            # 处理响应
            resp_str = str(response)
            # 如果响应包含 RCONMessage 对象表示，通常意味着没有文本返回（这是正常的，因为服务器重启了）
            if not resp_str or "<RCONMessage" in resp_str:
                return "指令已发送。服务器正在重启..."
            
            return f"指令已发送。服务器响应: {resp_str}"
        
        except (socket.timeout, ConnectionResetError, ConnectionAbortedError, BrokenPipeError, EOFError):
            # 在执行指令期间发生连接中断/超时，通常意味着服务器收到指令后立即重启并断开了连接
            return "指令已发送。服务器正在重启..."
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return f"指令执行出错: {type(e).__name__} - {e}"
        finally:
            # 确保关闭连接
            rcon.close()
