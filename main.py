from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import os
import asyncio
from .config_manager import ConfigManager
from .l4d2_query import L4D2Server

@register("l4d2_query", "YourName", "L4D2服务器查询插件", "1.0.0")
class L4D2Plugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.config_path = os.path.join(os.path.dirname(__file__), "config.json")
        self.cfg = ConfigManager(self.config_path)

    async def _check_group(self, event: AstrMessageEvent) -> bool:
        """检查是否在允许的群组中"""
        allowed_group = self.cfg.get_group_id()
        if not allowed_group:
            return True # 未配置群号，默认允许所有
        
        # 尝试获取群号，具体API可能因版本而异，这里尝试通用获取方式
        # 假设 event.message_obj.group_id 存在
        try:
            # 不同的适配器可能有不同的字段，这里做一个简单的尝试
            # 比如 event.message_obj.group_id 或者 event.session.group_id
            current_group = getattr(event.message_obj, "group_id", None)
            if current_group and str(current_group) == str(allowed_group):
                return True
        except:
            pass
        
        return False

    @filter.command("查询")
    async def query_server(self, event: AstrMessageEvent):
        """查询指定L4D2服务器状态。用法：/查询 [服务器名]"""
        if not await self._check_group(event):
            return

        server_name = event.message_str.strip()
        if not server_name:
            yield event.plain_result("请输入服务器名称，例如：/查询 主服务器")
            return

        server_config = self.cfg.get_server_by_name(server_name)
        if not server_config:
            yield event.plain_result(f"未找到名为 '{server_name}' 的服务器，请检查配置。")
            return

        server = L4D2Server(server_config["name"], server_config["address"])
        
        # 异步执行查询，避免阻塞主线程
        yield event.plain_result(f"正在查询 {server_name}，请稍候...")
        
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, server.query_info)
        
        if not info:
            yield event.plain_result(f"无法连接到服务器 {server_name}，可能服务器离线或网络问题。")
            return

        players = await loop.run_in_executor(None, server.query_players)
        
        # 构建回复消息
        msg = f"服务器: {info['server_name']}\n"
        msg += f"地图: {info['map_name']}\n"
        msg += f"人数: {info['player_count']}/{info['max_players']}\n"
        msg += f"延迟: {info['ping']}ms\n"
        
        if players:
            msg += "\n在线玩家:\n"
            for p in players:
                # 转换时长格式
                duration = int(p['duration'])
                m, s = divmod(duration, 60)
                h, m = divmod(m, 60)
                time_str = f"{h}h {m}m" if h > 0 else f"{m}m {s}s"
                msg += f"- {p['name']} (得分: {p['score']}, 时长: {time_str})\n"
        else:
            msg += "\n当前无玩家在线。"

        yield event.plain_result(msg)

    @filter.command("综合查询")
    async def query_all(self, event: AstrMessageEvent):
        """查询所有配置的L4D2服务器简略状态"""
        if not await self._check_group(event):
            return

        servers_config = self.cfg.get_servers()
        if not servers_config:
            yield event.plain_result("未配置任何服务器。")
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

    def _query_server_brief(self, server: L4D2Server):
        """辅助函数：同步查询单个服务器简略信息"""
        info = server.query_info()
        if info:
            return (True, info['player_count'], info['max_players'], f"[{server.name}] {info['server_name']} {info['player_count']}/{info['max_players']}")
        else:
            return (False, 0, 0, f"[{server.name}] 离线或无法连接")
