import socket
import valve.rcon

class RCONClient:
    def __init__(self, ip: str, port: int, password: str, timeout: float = 5.0):
        self.ip = ip
        self.port = port
        self.password = password
        self.timeout = timeout

    def execute(self, command: str) -> str:
        """通过 RCON 执行指令"""
        rcon = valve.rcon.RCON((self.ip, self.port), self.password, timeout=self.timeout)
        
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
            response = rcon.execute(command)
            
            # 处理响应
            resp_str = str(response)
            # 如果响应包含 RCONMessage 对象表示，通常意味着没有文本返回
            if not resp_str or "<RCONMessage" in resp_str:
                if command == "_restart":
                    return "指令已发送。服务器正在重启..."
                return "指令已发送。服务器无文本响应。"
            
            return f"服务器响应: {resp_str}"
        
        except (socket.timeout, ConnectionResetError, ConnectionAbortedError, BrokenPipeError, EOFError, valve.rcon.RCONCommunicationError):
            # 特殊处理重启指令导致的连接断开
            if command == "_restart":
                return "指令已发送。服务器正在重启..."
            return "指令发送后连接断开，可能服务器已崩溃或重启。"
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return f"指令执行出错: {type(e).__name__} - {e}"
        finally:
            # 确保关闭连接
            rcon.close()
