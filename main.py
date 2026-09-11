from astrbot.api.all import *
from astrbot.api.event import filter
from astrbot.api.star import StarTools
from astrbot.api.web import error_response, json_response, request
from astrbot.core.utils.session_waiter import (
    SessionController,
    SessionFilter,
    USER_SESSIONS,
    session_waiter,
)
import asyncio
import re
from .l4d2_query import L4D2Server
from .config_manager import (
    ConfigConflictError,
    ConfigManager,
    ConfigValidationError,
)
from .panel_client import (
    PanelClient,
    PanelError,
    SelectionError,
    build_file_list_lines,
    filter_supported_items,
    is_all_selection,
    parse_number_selection,
)
from .workshop_utils import WorkshopTools
from .heybox_voice import HeyboxVoiceClient

PLUGIN_NAME = "astrbot_plugin_l4d2_query"


class _MemberSessionFilter(SessionFilter):
    """按“群 + 发送者”区分等待会话，避免同群多人互相打断。"""

    def filter(self, event: AstrMessageEvent) -> str:
        return f"{event.unified_msg_origin}:{event.get_sender_id()}"


async def _cancel_existing_session(session_id: str) -> None:
    """结束同一会话中尚未完成的等待，并等它清理完毕后再开启新会话。"""
    existing = USER_SESSIONS.get(session_id)
    if existing is None:
        return
    try:
        existing.session_controller.stop()
    except Exception:
        return
    for _ in range(20):
        if USER_SESSIONS.get(session_id) is None:
            return
        await asyncio.sleep(0.01)


@register("l4d2_query", "LaoYutang", "L4D2服务器查询插件", "1.5.0")
class L4D2Plugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 配置存放在 data/plugin_data 下，更新插件时不会被整目录替换掉。
        self.config_path = str(StarTools.get_data_dir(PLUGIN_NAME) / "config.json")
        logger.info(f"L4D2 查询插件配置文件：{self.config_path}")
        self.cfg = ConfigManager(self.config_path)
        self.workshop = WorkshopTools()
        self.hh_voice = HeyboxVoiceClient(self.cfg.get_hh_bot_id(), self.cfg.get_hh_bot_token())
        context.register_web_api(
            f"/{PLUGIN_NAME}/config",
            self.page_get_config,
            ["GET"],
            "读取 L4D2 查询插件配置",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/config",
            self.page_save_config,
            ["POST"],
            "保存 L4D2 查询插件配置",
        )

    async def page_get_config(self):
        """配置 Page：从插件数据目录读取最新内容。"""
        try:
            config, revision = self.cfg.reload_config()
            return json_response(
                {
                    "config": config,
                    "revision": revision,
                    "filename": "config.json",
                }
            )
        except (OSError, ValueError) as exc:
            return error_response(f"读取 config.json 失败：{exc}", status_code=500)

    async def page_save_config(self):
        """配置 Page：校验并原子替换插件数据目录下的 config.json。"""
        payload = await request.json(default={})
        if not isinstance(payload, dict) or "config" not in payload:
            return error_response("请求中缺少 config 对象", status_code=400)

        try:
            config, revision = self.cfg.replace_config(
                payload["config"], payload.get("revision")
            )
            # 凭据变更后立即应用，无需用户重载整个插件。
            self.hh_voice = HeyboxVoiceClient(
                self.cfg.get_hh_bot_id(), self.cfg.get_hh_bot_token()
            )
            return json_response(
                {
                    "saved": True,
                    "config": config,
                    "revision": revision,
                    "filename": "config.json",
                }
            )
        except ConfigValidationError as exc:
            return error_response(str(exc), status_code=400)
        except ConfigConflictError as exc:
            return error_response(str(exc), status_code=409)
        except (OSError, TypeError, ValueError):
            logger.exception("保存 L4D2 插件配置失败")
            return error_response("保存 config.json 失败，请查看 AstrBot 日志", status_code=500)

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

    def _get_server_config_by_name(self, servers: list, target_name: str):
        """按现有查询规则匹配服务器名（忽略空格）"""
        for server in servers:
            if server.get("name", "").replace(" ", "") == target_name:
                return server
        return None

    def _is_voice_configured(self, group_conf: dict, server_conf: dict) -> bool:
        """检查黑盒语音配置是否足够查询指定服务器频道"""
        return bool(
            self.hh_voice.enabled()
            and group_conf.get("hh_room_id")
            and server_conf.get("hh_channel_id")
        )

    async def _get_voice_count(self, group_conf: dict, server_conf: dict):
        """获取语音频道在线人数，失败时返回 None 以保持主查询不受影响"""
        if not self._is_voice_configured(group_conf, server_conf):
            return None
        user_ids = await self.hh_voice.get_channel_user_ids(
            str(group_conf.get("hh_room_id")),
            str(server_conf.get("hh_channel_id"))
        )
        if user_ids is None:
            return None
        return len(user_ids)

    async def _get_voice_names(self, group_conf: dict, server_conf: dict):
        """获取语音频道在线用户名，失败时返回 None"""
        if not self._is_voice_configured(group_conf, server_conf):
            return None
        return await self.hh_voice.get_channel_user_names(
            str(group_conf.get("hh_room_id")),
            str(server_conf.get("hh_channel_id"))
        )

    def _format_player_name(self, name: str) -> str:
        """根据安全模式配置格式化玩家名"""
        if not self.cfg.get_safe_mode() or len(name) <= 2:
            return name
        return f"{name[0]}{'*' * (len(name) - 2)}{name[-1]}"

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
        server_config = self._get_server_config_by_name(servers, target_name)
        
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

        players_task = loop.run_in_executor(None, server.query_players)
        voice_count_task = self._get_voice_count(group_conf, server_config)
        players, voice_count = await asyncio.gather(players_task, voice_count_task)
        
        msg = f"服务器: {info['server_name']}\n"
        msg += f"地图: {info['map_name']}\n"
        player_line = f"人数: {info['player_count']}/{info['max_players']}"
        if voice_count is not None:
            player_line += f" (🎧{voice_count})"
        msg += player_line + "\n"
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
                msg += f"- {self._format_player_name(p['name'])} ({time_str})\n"
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

    @filter.regex(r"^语音\s*(.+)$")
    async def query_voice_channel(self, event: AstrMessageEvent, *args, **kwargs):
        """查询指定服务器对应黑盒语音频道的在线名单。用法：语音 [服务器名]"""
        group_conf = self._get_group_config(event)
        if not group_conf:
            return

        server_name = event.message_str.replace("语音", "", 1).strip()
        target_name = server_name.replace(" ", "")
        if not target_name:
            return

        server_config = self._get_server_config_by_name(group_conf.get("servers", []), target_name)
        if not server_config:
            return

        names = await self._get_voice_names(group_conf, server_config)
        if names is None:
            return

        server_display_name = server_config.get("name", target_name)
        if not names:
            yield event.plain_result(f"{server_display_name} 语音频道当前无人在线。")
            return

        msg = f"=== {server_display_name} 语音频道 ===\n"
        msg += f"在线人数: {len(names)}\n"
        for name in names:
            msg += f"- {name}\n"
        yield event.plain_result(msg.strip())

    @filter.regex(r"^connect\s+([a-zA-Z0-9.-]+(?::\d+)?)$")
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
                msg += f"- {self._format_player_name(p['name'])} ({time_str})\n"
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
        voice_tasks = [
            self._get_voice_count(group_conf, conf) if res.get("online") else asyncio.sleep(0, result=None)
            for conf, res in zip(servers_config, results)
        ]
        voice_counts = await asyncio.gather(*voice_tasks)
        
        total_servers = len(servers_config)
        online_servers = 0
        total_players = 0
        total_slots = 0
        
        # 预处理数据，计算对齐所需的宽度
        processed_servers = []
        max_player_len = 0
        
        for res, voice_count in zip(results, voice_counts):
            if voice_count is not None:
                res["_voice_count"] = voice_count
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
                
                voice_part = ""
                if "_voice_count" in res:
                    voice_part = f"   🎧{res['_voice_count']}"

                # 地图名
                map_name = res["_map_display"]
                
                # 别名和服务器名之间增加空格，第二行人数，第三行地图
                line = f"{prefix} {s_name}\n{padding}{p_str}{p_padding}{voice_part}\n{padding}{map_name}"
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

    @filter.regex(r"https?://qfile\.qq\.com/q/[A-Za-z0-9_-]+")
    async def flash_transfer_upload(self, event: AstrMessageEvent, *args, **kwargs):
        """管理员发送 QQ 闪传链接后，选择服务器与文件并交由面板创建下载任务。"""
        group_conf = self._get_group_config(event)
        if not group_conf:
            return
        if not self._check_permission(event, group_conf.get("admin_users", [])):
            return

        match = re.search(r"https?://qfile\.qq\.com/q/[A-Za-z0-9_-]+", event.message_str)
        if not match:
            return
        share_url = match.group(0)

        panel_servers = [
            server
            for server in group_conf.get("servers", [])
            if str(server.get("panel_url", "")).strip()
            and str(server.get("panel_token", "")).strip()
        ]
        if not panel_servers:
            yield event.plain_result(
                "本群尚未配置带面板地址和面板凭据的服务器，请先在插件配置页填写后再试。"
            )
            return

        session_id = f"{event.unified_msg_origin}:{event.get_sender_id()}"
        await _cancel_existing_session(session_id)

        server_choice = None
        selected_indices = None

        @session_waiter(timeout=30)
        async def select_server(controller: SessionController, wait_event: AstrMessageEvent):
            nonlocal server_choice
            try:
                indices = parse_number_selection(
                    wait_event.message_str, len(panel_servers), allow_multiple=False
                )
            except SelectionError as exc:
                await wait_event.send(wait_event.plain_result(str(exc)))
                controller.stop()
                return
            server_choice = panel_servers[indices[0]]
            controller.stop()

        try:
            lines = [
                "检测到 QQ 闪传链接，请选择要上传的服务器"
                "（回复序号，输入其他内容取消，30 秒内有效）："
            ]
            for index, server in enumerate(panel_servers, start=1):
                lines.append(f"{index}. {server.get('name', '')}")
            yield event.plain_result("\n".join(lines))

            await select_server(event, session_filter=_MemberSessionFilter())
            if server_choice is None:
                return

            yield event.plain_result("正在解析闪传链接，请稍候...")

            client = PanelClient(
                str(server_choice.get("panel_url", "")),
                str(server_choice.get("panel_token", "")),
            )
            try:
                items = await client.parse_download_link(share_url)
            except PanelError as exc:
                yield event.plain_result(f"解析闪传链接失败：{exc}")
                return

            supported_items = filter_supported_items(items)
            if not supported_items:
                yield event.plain_result("未解析到可下载的文件（仅支持 .vpk/.zip/.rar/.7z）。")
                return

            server_display = str(server_choice.get("name", "")).strip()
            file_lines = build_file_list_lines(supported_items)
            yield event.plain_result(
                f"{server_display} 解析成功，共 {len(supported_items)} 个可下载文件，"
                "请选择要下载的文件（回复序号，多个用逗号分隔；回复“全部”下载全部；"
                "输入其他内容取消，30 秒内有效）："
            )
            for start in range(0, len(file_lines), 30):
                yield event.plain_result("\n".join(file_lines[start:start + 30]))

            @session_waiter(timeout=30)
            async def select_files(controller: SessionController, wait_event: AstrMessageEvent):
                nonlocal selected_indices
                if is_all_selection(wait_event.message_str):
                    selected_indices = list(range(len(supported_items)))
                    controller.stop()
                    return
                try:
                    selected_indices = parse_number_selection(
                        wait_event.message_str, len(supported_items)
                    )
                except SelectionError as exc:
                    await wait_event.send(wait_event.plain_result(str(exc)))
                    controller.stop()
                    return
                controller.stop()

            await select_files(event, session_filter=_MemberSessionFilter())
            if selected_indices is None:
                return

            results = []
            for index in selected_indices:
                item = supported_items[index]
                filename = str(
                    item.get("filename") or item.get("title") or "downloaded_file"
                ).strip()
                try:
                    await client.add_download_task(
                        str(item.get("file_url", "")),
                        filename,
                        str(item.get("referer", "")),
                    )
                    results.append((filename, True, ""))
                except PanelError as exc:
                    results.append((filename, False, str(exc)))

            yield event.plain_result(self._format_flash_transfer_result(results))
        except TimeoutError:
            yield event.plain_result("超时取消")
        finally:
            # 放在最后调用：等所有回复发送完成后再终止事件传播，避免影响本插件消息的发送
            event.stop_event()

    @staticmethod
    def _format_flash_transfer_result(results: list) -> str:
        """汇总面板下载任务的添加结果。"""
        added = [name for name, ok, _ in results if ok]
        failed = [(name, message) for name, ok, message in results if not ok]

        lines = []
        if added:
            lines.append(f"已提交 {len(added)} 个下载任务：")
            lines.extend(f"- {name}" for name in added)
        if failed:
            if lines:
                lines.append("")
            lines.append(f"提交失败 {len(failed)} 个：")
            lines.extend(f"- {name}：{message}" for name, message in failed)
        if not lines:
            lines.append("没有提交任何下载任务。")
        return "\n".join(lines)
