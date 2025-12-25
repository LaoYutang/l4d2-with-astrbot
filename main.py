from astrbot.api.all import *
from astrbot.api.event import filter
import os
import asyncio
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

        server = L4D2Server(server_config["name"], server_config["address"])
        
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
        
        for conf in servers_config:
            server = L4D2Server(conf["name"], conf["address"])
            tasks.append(loop.run_in_executor(None, self._query_server_brief, server))

        results = await asyncio.gather(*tasks)
        
        total_servers = len(servers_config)
        online_servers = 0
        total_players = 0
        total_slots = 0
        
        server_lines = []
        for is_online, p_count, max_p, line in results:
            if is_online:
                online_servers += 1
                total_players += p_count
                total_slots += max_p
            server_lines.append(line)
            
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

    def _query_server_brief(self, server: L4D2Server):
        """辅助函数：同步查询单个服务器简略信息"""
        info = server.query_info()
        if info:
            return (True, info['player_count'], info['max_players'], f"[{server.name}] {info['server_name']} {info['player_count']}/{info['max_players']}")
        else:
            return (False, 0, 0, f"[{server.name}] 离线或无法连接")

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

    @filter.regex(r"https?://steamcommunity\.com/sharedfiles/filedetails/\?id=(\d+)")
    async def parse_workshop_link(self, event: AstrMessageEvent, match: re.Match):
        """解析创意工坊链接"""
        url = match.group(0)
        yield event.plain_result("正在解析创意工坊链接，请稍候...")
        
        results, type_str = await self.workshop.process_url(url)
        
        if not results:
            yield event.plain_result(f"解析失败: {type_str}")
            return

        msg = f"=== 创意工坊{type_str}解析 ===\n"
        for item in results:
            title = item.get("title", "未知标题")
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
