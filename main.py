from astrbot.api.all import *
from astrbot.api.event import filter
import os
import asyncio
import re
from .l4d2_query import L4D2Server
from .config_manager import ConfigManager
from .workshop_utils import WorkshopTools

@register("l4d2_query", "YourName", "L4D2服务器查询插件", "1.0.0")
class L4D2Plugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.config_path = os.path.join(os.path.dirname(__file__), "config.json")
        self.cfg = ConfigManager(self.config_path)
        self.workshop = WorkshopTools()

    def _get_group_config(self, event: AstrMessageEvent):
        """获取当前群的配置"""
        try:
            current_group = getattr(event.message_obj, "group_id", None)
            if not current_group:
                return None
            return self.cfg.get_group_config(str(current_group))
        except:
            pass
        return None

    @filter.regex(r"^查询\s*(.+)$")
    async def query_server(self, event: AstrMessageEvent, *args, **kwargs):
        """查询指定L4D2服务器状态。用法：查询 [服务器名]"""
        group_conf = self._get_group_config(event)
        if not group_conf:
            # 如果不在配置的群组中，不响应
            return

        # 解析参数，移除指令部分
        # regex 保证了开头是 "查询"，后面有内容
        server_name = event.message_str.replace("查询", "", 1).strip()
        target_name = server_name.replace(" ", "")
        
        if not target_name:
             # 理论上 regex 保证了有内容，但 strip 后可能为空
            yield event.plain_result("请输入服务器名称，例如：查询 主服务器")
            return

        servers = group_conf.get("servers", [])
        server_config = None
        for s in servers:
            if s.get("name", "").replace(" ", "") == target_name:
                server_config = s
                break
        
        if not server_config:
            # 未找到服务器，静默返回
            return

        map_name_url = self.cfg.get_map_name_url()
        server = L4D2Server(server_config["name"], server_config["address"], map_name_url)
        
        yield event.plain_result(f"正在查询 {server_config['name']}，请稍候...")
        
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, server.query_info)
        
        if not info:
            yield event.plain_result(f"无法连接到服务器 {server_config['name']}，可能服务器离线或网络问题。")
            return

        players = await loop.run_in_executor(None, server.query_players)
        
        msg = f"服务器: {info['server_name']}\n"
        msg += f"地图: {info['map_name']}\n"
        msg += f"人数: {info['player_count']}/{info['max_players']}\n"
        msg += f"延迟: {info['ping']}ms\n"
        
        if players:
            msg += "\n在线玩家:\n"
            for p in players:
                duration = int(p['duration'])
                m, s = divmod(duration, 60)
                h, m = divmod(m, 60)
                d, h = divmod(h, 24)
                if d > 0:
                    time_str = f"{d}:{h:02d}:{m:02d}:{s:02d}"
                elif h > 0:
                    time_str = f"{h}:{m:02d}:{s:02d}"
                else:
                    time_str = f"{m}:{s:02d}"
                msg += f"- {p['name']} ({time_str})\n"
        else:
            msg += "\n当前无玩家在线。"

        base_url = self.cfg.get_connect_base_url()
        if base_url:
            if base_url.endswith("/"):
                msg += f"\n点击直连: {base_url}{server.ip}:{server.port}"
            else:
                msg += f"\n点击直连: {base_url}/{server.ip}:{server.port}"
        else:
            msg += f"\n连接指令: connect {server.ip}:{server.port}"
        yield event.plain_result(msg)

    @filter.regex(r"^connect\s+([a-zA-Z0-9\.:]+)$")
    async def query_connect_info(self, event: AstrMessageEvent, *args, **kwargs):
        """查询 connect 指令中的服务器信息"""
        address = event.message_str.replace("connect", "", 1).strip()
        
        # 创建临时服务器对象进行查询
        # 名称暂时用 "Unknown Server" 代替，查询成功后会更新
        map_name_url = self.cfg.get_map_name_url()
        temp_server = L4D2Server("Unknown Server", address, map_name_url)
        
        yield event.plain_result(f"正在查询 {address}，请稍候...")
        
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, temp_server.query_info)
        
        if not info:
            yield event.plain_result(f"无法连接到服务器 {address}，可能服务器离线或网络问题。")
            return

        players = await loop.run_in_executor(None, temp_server.query_players)
        
        msg = f"服务器: {info['server_name']}\n"
        msg += f"地址: {address}\n"
        msg += f"地图: {info['map_name']}\n"
        msg += f"人数: {info['player_count']}/{info['max_players']}\n"
        msg += f"延迟: {info['ping']}ms\n"
        
        if players:
            msg += "\n在线玩家:\n"
            for p in players:
                duration = int(p['duration'])
                m, s = divmod(duration, 60)
                h, m = divmod(m, 60)
                d, h = divmod(h, 24)
                if d > 0:
                    time_str = f"{d}:{h:02d}:{m:02d}:{s:02d}"
                elif h > 0:
                    time_str = f"{h}:{m:02d}:{s:02d}"
                else:
                    time_str = f"{m}:{s:02d}"
                msg += f"- {p['name']} ({time_str})\n"
        else:
            msg += "\n当前无玩家在线。"

        base_url = self.cfg.get_connect_base_url()
        if base_url:
            if base_url.endswith("/"):
                msg += f"\n点击直连: {base_url}{temp_server.ip}:{temp_server.port}"
            else:
                msg += f"\n点击直连: {base_url}/{temp_server.ip}:{temp_server.port}"
        else:
            msg += f"\n连接指令: connect {temp_server.ip}:{temp_server.port}"

        yield event.plain_result(msg)

    @filter.regex(r"^综合查询$")
    async def query_all(self, event: AstrMessageEvent, *args, **kwargs):
        """查询所有配置的L4D2服务器简略状态"""
        group_conf = self._get_group_config(event)
        if not group_conf:
            return

        servers_config = group_conf.get("servers", [])
        if not servers_config:
            yield event.plain_result("本群未配置任何服务器。")
            return

        yield event.plain_result("正在查询所有服务器状态...")

        loop = asyncio.get_running_loop()
        tasks = []
        map_name_url = self.cfg.get_map_name_url()
        
        for conf in servers_config:
            server = L4D2Server(conf["name"], conf["address"], map_name_url)
            tasks.append(loop.run_in_executor(None, self._query_server_brief, server))

        results = await asyncio.gather(*tasks)
        
        total_servers = len(servers_config)
        online_servers = 0
        total_players = 0
        total_slots = 0
        
        # 预处理数据，计算对齐所需的宽度
        processed_servers = []
        max_player_len = 0
        
        for res in results:
            if res["online"]:
                # 截断地图名，最大显示宽度15
                trunc_map = self._truncate_text(res["map_name"], 15)
                
                # 记录人数显示字符串及其长度
                p_str = f"{res['player_count']}/{res['max_players']}"
                if len(p_str) > max_player_len:
                    max_player_len = len(p_str)
                
                res["_map_display"] = trunc_map
                res["_player_str"] = p_str
            processed_servers.append(res)
        
        server_lines = []
        for res in processed_servers:
            if res["online"]:
                online_servers += 1
                total_players += res["player_count"]
                total_slots += res["max_players"]
                
                s_name = res["server_name"]
                s_name = self._truncate_text(s_name, 20)
                
                # 计算前缀宽度，用于第二行缩进
                prefix = f"[{res['alias']}]"
                prefix_width = self._get_text_width(prefix)
                # 增加一个空格的缩进，以匹配第一行的空格
                padding = self._make_padding(prefix_width) + " "
                
                # 人数对齐处理 (左对齐)
                p_str = res["_player_str"]
                # 针对非等宽字体优化：少一个字符补两个空格
                diff = max_player_len - len(p_str)
                p_padding = " " * (diff * 2)
                
                # 地图名
                map_name = res["_map_display"]
                
                # 别名和服务器名之间增加空格，人数放前面(左对齐)，地图放后面
                line = f"{prefix} {s_name}\n{padding}{p_str}{p_padding}   {map_name}"
                server_lines.append(line)
            else:
                server_lines.append(f"[{res['alias']}] 离线或无法连接")
            
        msg = "=== L4D2 服务器概览 ===\n"
        msg += f"服务器: {online_servers}/{total_servers} 在线\n"
        msg += f"人数: {total_players}/{total_slots}\n"
        msg += "-" * 25 + "\n"
        for line in server_lines:
            msg += line + "\n"
        
        yield event.plain_result(msg)

    @filter.regex(r"^(服务器列表|服务器地址|连接指令)$")
    async def list_servers(self, event: AstrMessageEvent, *args, **kwargs):
        """列出所有服务器的连接地址"""
        group_conf = self._get_group_config(event)
        if not group_conf:
            return

        servers_config = group_conf.get("servers", [])
        if not servers_config:
            yield event.plain_result("本群未配置任何服务器。")
            return

        connect_base_url = self.cfg.get_connect_base_url()
        
        msg = "=== 服务器列表 ===\n"
        if connect_base_url:
            msg += "点击下方链接连接服务器：\n"

        for conf in servers_config:
            if connect_base_url:
                base_url = connect_base_url.rstrip('/')
                msg += f"[{conf['name']}] {base_url}/{conf['address']}\n"
            else:
                msg += f"[{conf['name']}] connect {conf['address']}\n"
        
        yield event.plain_result(msg)

    def _get_text_width(self, text: str) -> int:
        """计算字符串显示宽度 (中文字符计为2，包含中文标点)"""
        width = 0
        for char in text:
            # 判断 汉字(\u4e00-\u9fff) 或 全角字符(\uff00-\uffef, 包含中文小括号)
            if '\u4e00' <= char <= '\u9fff' or '\uff00' <= char <= '\uffef':
                width += 2
            else:
                width += 1
        return width

    def _truncate_text(self, text: str, max_width: int) -> str:
        """根据显示宽度截断字符串"""
        if self._get_text_width(text) <= max_width:
            return text
        
        current_width = 0
        result = ""
        
        for char in text:
            # 保持一致的宽度计算逻辑
            char_width = 2 if ('\u4e00' <= char <= '\u9fff' or '\uff00' <= char <= '\uffef') else 1
            if current_width + char_width > max_width:
                return result + "..."
            current_width += char_width
            result += char
            
        return result

    def _make_padding(self, width: int) -> str:
        """生成填充字符串，优先使用全角空格"""
        full_spaces = width // 2
        half_spaces = width % 2
        return "\u3000" * full_spaces + " " * half_spaces

    def _query_server_brief(self, server: L4D2Server):
        """辅助函数：同步查询单个服务器简略信息"""
        info = server.query_info()
        if info:
            map_name = info['map_name']
            if "|" in map_name:
                map_name = map_name.split("|")[0].strip()
            
            return {
                "online": True,
                "alias": server.name,
                "server_name": info['server_name'],
                "map_name": map_name,
                "player_count": info['player_count'],
                "max_players": info['max_players']
            }
        else:
            return {
                "online": False,
                "alias": server.name
            }

    def _check_permission(self, event: AstrMessageEvent, admin_list: list) -> bool:
        """检查发送者是否在管理员列表中"""
        try:
            user_id = None
            obj = event.message_obj
            
            # 尝试获取 sender
            sender = None
            if isinstance(obj, dict):
                sender = obj.get("sender")
            elif hasattr(obj, "sender"):
                sender = getattr(obj, "sender")
            
            if sender:
                if isinstance(sender, dict):
                    user_id = sender.get("user_id")
                elif hasattr(sender, "user_id"):
                    user_id = getattr(sender, "user_id")
            
            print(f"[L4D2Plugin] Debug - User ID: {user_id}, Admin List: {admin_list}")
            
            if user_id and str(user_id) in [str(uid) for uid in admin_list]:
                return True
            
            return False
        except Exception as e:
            print(f"[L4D2Plugin] Error checking permission: {e}")
            return False

    @filter.regex(r"^设置\s*(.+)$")
    async def rcon_command(self, event: AstrMessageEvent, *args, **kwargs):
        """向指定服务器发送RCON指令。用法：设置 [服务器名] [指令]"""
        group_conf = self._get_group_config(event)
        if not group_conf:
            return

        # 移除指令前缀
        content = event.message_str.replace("设置", "", 1).strip()
        
        servers = group_conf.get("servers", [])
        matched_server = None
        command = ""

        # 策略1：尝试匹配服务器名称前缀 (支持 "设置1服 status" 和 "设置 1服 status")
        # 按名称长度倒序，优先匹配长名字
        sorted_servers = sorted(servers, key=lambda s: len(s.get("name", "")), reverse=True)
        
        for s in sorted_servers:
            s_name = s.get("name", "")
            if not s_name: continue
            
            # 尝试匹配完整名称
            if content.startswith(s_name):
                matched_server = s
                command = content[len(s_name):].strip()
                break
            
            # 尝试匹配去空格名称 (例如配置为 "My Server"，输入 "MyServer status")
            s_name_nospace = s_name.replace(" ", "")
            if content.startswith(s_name_nospace):
                matched_server = s
                command = content[len(s_name_nospace):].strip()
                break
        
        # 策略2：如果前缀匹配失败，尝试旧的空格分割逻辑 (作为后备)
        if not matched_server:
            parts = content.split(" ", 1)
            if len(parts) >= 2:
                target_name = parts[0].replace(" ", "")
                cmd_part = parts[1].strip()
                for s in servers:
                    if s.get("name", "").replace(" ", "") == target_name:
                        matched_server = s
                        command = cmd_part
                        break

        if not matched_server:
            yield event.plain_result("未找到指定名称的服务器。")
            return

        if not command:
             yield event.plain_result("请输入要执行的指令。")
             return

        # 检查权限
        admin_users = group_conf.get("admin_users", [])
        if not self._check_permission(event, admin_users):
            yield event.plain_result("权限不足：您不在管理员列表中。")
            return

        rcon_password = matched_server.get("rcon_password")
        if not rcon_password:
            yield event.plain_result(f"服务器 {matched_server['name']} 未配置 RCON 密码，无法执行指令。")
            return

        server = L4D2Server(matched_server["name"], matched_server["address"])
        
        yield event.plain_result(f"正在向 {matched_server['name']} 发送指令: {command} ...")
        
        loop = asyncio.get_running_loop()
        try:
            # 设置 15 秒的总超时时间
            result = await asyncio.wait_for(
                loop.run_in_executor(None, server.execute_rcon, rcon_password, command),
                timeout=15.0
            )
        except asyncio.TimeoutError:
            result = "操作超时：连接服务器耗时过长，请检查服务器状态或网络连接。"
        except Exception as e:
            import traceback
            traceback.print_exc()
            result = f"执行出错: {type(e).__name__} - {e}"
        
        yield event.plain_result(result)

    @filter.regex(r"^重启\s*(.+)$")
    async def restart_server(self, event: AstrMessageEvent, *args, **kwargs):
        """重启指定服务器。用法：重启 [服务器名]"""
        # 打印调试信息，查看是否有额外参数
        if args:
            print(f"[L4D2Plugin] Debug - Restart args: {args}")

        group_conf = self._get_group_config(event)
        if not group_conf:
            return

        server_name = event.message_str.replace("重启", "", 1).strip()
        target_name = server_name.replace(" ", "")
        
        if not target_name:
            yield event.plain_result("请输入服务器名称，例如：重启 主服务器")
            return

        servers = group_conf.get("servers", [])
        server_config = None
        for s in servers:
            if s.get("name", "").replace(" ", "") == target_name:
                server_config = s
                break
        
        if not server_config:
            # 未找到服务器，静默返回
            return

        # 检查权限
        admin_users = group_conf.get("admin_users", [])
        if not self._check_permission(event, admin_users):
            yield event.plain_result("权限不足：您不在管理员列表中。")
            return

        rcon_password = server_config.get("rcon_password")
        if not rcon_password:
            yield event.plain_result(f"服务器 {server_config['name']} 未配置 RCON 密码，无法执行重启。")
            return

        server = L4D2Server(server_config["name"], server_config["address"])
        
        yield event.plain_result(f"正在尝试重启 {server_config['name']}...")
        
        loop = asyncio.get_running_loop()
        try:
            # 设置 15 秒的总超时时间，防止底层库卡死
            result = await asyncio.wait_for(
                loop.run_in_executor(None, server.restart, rcon_password),
                timeout=15.0
            )
        except asyncio.TimeoutError:
            result = "操作超时：连接服务器耗时过长，请检查服务器状态或网络连接。"
        
        yield event.plain_result(result)

    @filter.regex(r"https?://steamcommunity\.com/(?:sharedfiles|workshop)/filedetails/\?id=(\d+)")
    async def parse_workshop_link(self, event: AstrMessageEvent, *args, **kwargs):
        """解析创意工坊链接"""
        # 手动匹配以获取 URL
        match = re.search(r"https?://steamcommunity\.com/(?:sharedfiles|workshop)/filedetails/\?id=(\d+)", event.message_str)
        if not match:
            return
            
        url = match.group(0)
        yield event.plain_result("正在解析创意工坊链接，请稍候...")
        
        results, type_str = await self.workshop.process_url(url)
        
        if not results:
            yield event.plain_result(f"解析失败: {type_str}")
            return

        msg = f"=== 创意工坊{type_str}解析 ===\n"
        for item in results:
            title = item.get("title", "未知标题")
            # 清理标题中的换行符
            if title:
                title = title.replace("\n", " ").replace("\r", "").strip()
                
            file_url = item.get("file_url", "")
            filename = item.get("filename", "")
            size = item.get("file_size", "未知大小")
            
            # 简单的文件名清理
            if filename:
                filename = filename.replace("\\", "/").split("/")[-1]
            
            msg += f"标题: {title}\n"
            msg += f"文件: {filename} ({size})\n"
            msg += f"下载: {file_url}\n"
            msg += "-" * 20 + "\n"
            
        yield event.plain_result(msg.strip())
