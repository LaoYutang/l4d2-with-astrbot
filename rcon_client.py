import socket
import struct
import random
import time

class SourceRCON:
    SERVERDATA_AUTH = 3
    SERVERDATA_EXECCOMMAND = 2
    SERVERDATA_AUTH_RESPONSE = 2
    SERVERDATA_RESPONSE_VALUE = 0

    def __init__(self, host, port, password, timeout=5.0):
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self.sock = None

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), self.timeout)
        self.sock.settimeout(self.timeout)

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None

    def _send_packet(self, packet_type, body):
        req_id = random.randint(1, 2147483647)
        if isinstance(body, str):
            body = body.encode('utf-8')
        
        # Packet Size = 4 (ID) + 4 (Type) + len(body) + 1 (null) + 1 (null)
        packet_size = 4 + 4 + len(body) + 2
        
        # pack: size, id, type
        header = struct.pack('<iii', packet_size, req_id, packet_type)
        data = header + body + b'\x00\x00'
        
        self.sock.sendall(data)
        return req_id

    def _read_packet(self):
        # Read Size (4 bytes)
        data = b''
        while len(data) < 4:
            chunk = self.sock.recv(4 - len(data))
            if not chunk:
                raise ConnectionResetError("Connection closed by server")
            data += chunk
        
        size = struct.unpack('<i', data)[0]
        
        # Read Body (Size bytes)
        data = b''
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise ConnectionResetError("Connection closed by server")
            data += chunk
            
        # Parse: ID (4), Type (4), Body (Rest)
        res_id = struct.unpack('<i', data[0:4])[0]
        res_type = struct.unpack('<i', data[4:8])[0]
        
        # Body is everything after first 8 bytes, minus the last 2 null bytes usually
        # But strictly speaking, it's a null-terminated string.
        # We just take everything up to the end-2 for safety, or strip nulls.
        body = data[8:-2]
        
        return res_id, res_type, body

    def authenticate(self):
        self._send_packet(self.SERVERDATA_AUTH, self.password)
        
        while True:
            rid, rtype, body = self._read_packet()
            # Wait for AUTH_RESPONSE
            if rtype == self.SERVERDATA_AUTH_RESPONSE:
                if rid == -1:
                    raise Exception("RCON 认证失败：密码错误")
                return True

    def execute(self, command):
        # 1. Send the command
        cmd_id = self._send_packet(self.SERVERDATA_EXECCOMMAND, command)
        
        # 2. Send a "Check" packet (empty RESPONSE_VALUE) to mark the end
        # This is a standard trick because Source RCON doesn't tell you when a multi-packet response ends.
        check_id = self._send_packet(self.SERVERDATA_RESPONSE_VALUE, "")
        
        response_buffer = b""
        
        while True:
            rid, rtype, body = self._read_packet()
            
            if rid == check_id:
                # We received the response to our check packet, so the previous command output is done.
                break
            elif rid == cmd_id:
                # This is part of the command output
                response_buffer += body
            elif rtype == self.SERVERDATA_RESPONSE_VALUE:
                # Sometimes ID might not match if server is weird, but usually it does.
                # Some servers just stream output.
                # But for safety, we only collect what matches our command ID or generic output if we are the only user.
                # Let's trust the ID for now.
                pass
                
        return response_buffer.decode('utf-8', errors='replace')

class RCONClient:
    def __init__(self, ip: str, port: int, password: str, timeout: float = 5.0):
        self.ip = ip
        self.port = port
        self.password = password
        self.timeout = timeout

    def execute(self, command: str) -> str:
        """通过 RCON 执行指令"""
        client = SourceRCON(self.ip, self.port, self.password, self.timeout)
        try:
            client.connect()
            client.authenticate()
            
            # 特殊处理重启指令
            if command == "_restart":
                try:
                    client._send_packet(client.SERVERDATA_EXECCOMMAND, command)
                    return "指令已发送。服务器正在重启..."
                except:
                    return "指令已发送。服务器正在重启..."

            response = client.execute(command)
            if not response:
                return "指令已发送。服务器无文本响应。"
            return f"服务器响应: {response}"
            
        except Exception as e:
            return f"RCON 执行出错: {e}"
        finally:
            client.close()
