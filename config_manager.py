import copy
import hashlib
import json
import os
import re
import tempfile
import threading
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse


class ConfigValidationError(ValueError):
    """配置内容不符合插件要求。"""


class ConfigConflictError(RuntimeError):
    """配置文件在页面打开后被其他操作修改。"""


class ConfigManager:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self._lock = threading.RLock()
        self.config = self._load_config()

    @staticmethod
    def default_config() -> Dict[str, Any]:
        return {
            "connectBaseUrl": "",
            "mapNameUrl": "",
            "safeMode": False,
            "hh_bot_id": "",
            "hh_bot_token": "",
            "group_configs": [
                {
                    "group_id": "12345678",
                    "hh_room_id": "",
                    "admin_users": [],
                    "servers": [
                        {
                            "name": "示例服务器",
                            "address": "127.0.0.1:27015",
                            "hh_channel_id": "",
                            "rcon_password": "your_rcon_password_here",
                        }
                    ],
                }
            ],
        }

    def _load_config(self) -> Dict[str, Any]:
        if not os.path.exists(self.config_path):
            default_config = self.default_config()
            self._save_config(default_config)
            return default_config

        try:
            return self._read_config_file()
        except (OSError, json.JSONDecodeError, ConfigValidationError):
            # 保持原有行为：启动不因配置损坏而中断，配置页会显示具体错误。
            return {}

    def _read_config_file(self) -> Dict[str, Any]:
        with open(self.config_path, "r", encoding="utf-8-sig") as config_file:
            config = json.load(config_file)
        if not isinstance(config, dict):
            raise ConfigValidationError("config.json 的根节点必须是对象")
        return config

    def _save_config(self, config: Dict[str, Any]) -> None:
        """在同目录原子写入，避免保存中断时留下半个 JSON 文件。"""
        config_dir = os.path.dirname(os.path.abspath(self.config_path))
        os.makedirs(config_dir, exist_ok=True)
        file_descriptor, temp_path = tempfile.mkstemp(
            dir=config_dir,
            prefix=f".{os.path.basename(self.config_path)}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as config_file:
                json.dump(config, config_file, indent=4, ensure_ascii=False)
                config_file.write("\n")
                config_file.flush()
                os.fsync(config_file.fileno())
            os.replace(temp_path, self.config_path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def _file_revision(self) -> str:
        if not os.path.exists(self.config_path):
            return "missing"
        digest = hashlib.sha256()
        with open(self.config_path, "rb") as config_file:
            for chunk in iter(lambda: config_file.read(64 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def reload_config(self) -> Tuple[Dict[str, Any], str]:
        """从磁盘重新载入配置，并返回页面使用的快照与版本。"""
        with self._lock:
            config = self._read_config_file()
            self.config = config
            return copy.deepcopy(config), self._file_revision()

    def replace_config(
        self, config: Dict[str, Any], expected_revision: Optional[str] = None
    ) -> Tuple[Dict[str, Any], str]:
        """校验并替换完整配置，保留未知字段以兼容后续扩展。"""
        normalized = self.validate_config(config)
        with self._lock:
            current_revision = self._file_revision()
            if expected_revision and expected_revision != current_revision:
                raise ConfigConflictError(
                    "config.json 已被其他操作修改，请重新载入后再保存"
                )
            self._save_config(normalized)
            self.config = normalized
            return copy.deepcopy(normalized), self._file_revision()

    @classmethod
    def validate_config(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(config, dict):
            raise ConfigValidationError("配置根节点必须是对象")

        normalized = copy.deepcopy(config)
        normalized["connectBaseUrl"] = cls._optional_url(
            config.get("connectBaseUrl", ""), "一键连接基础 URL"
        )
        normalized["mapNameUrl"] = cls._optional_url(
            config.get("mapNameUrl", ""), "地图名称 API URL"
        )
        normalized["safeMode"] = cls._boolean(
            config.get("safeMode", False), "玩家名脱敏"
        )
        normalized["hh_bot_id"] = cls._string(
            config.get("hh_bot_id", ""), "黑盒机器人 ID"
        )
        normalized["hh_bot_token"] = cls._string(
            config.get("hh_bot_token", ""), "黑盒机器人 Token"
        )

        group_configs = config.get("group_configs", [])
        if not isinstance(group_configs, list):
            raise ConfigValidationError("群组配置必须是数组")

        normalized_groups = []
        known_group_ids = set()
        for group_index, group in enumerate(group_configs, start=1):
            label = f"第 {group_index} 个群组"
            if not isinstance(group, dict):
                raise ConfigValidationError(f"{label}必须是对象")

            group_id = cls._identifier(group.get("group_id"), f"{label}的群组 ID")
            if group_id in known_group_ids:
                raise ConfigValidationError(f"群组 ID {group_id} 重复")
            known_group_ids.add(group_id)

            normalized_group = copy.deepcopy(group)
            normalized_group["group_id"] = group_id
            normalized_group["hh_room_id"] = cls._string(
                group.get("hh_room_id", ""), f"群组 {group_id} 的黑盒房间 ID"
            )
            normalized_group["admin_users"] = cls._identifier_list(
                group.get("admin_users", []), f"群组 {group_id} 的管理员列表"
            )

            servers = group.get("servers", [])
            if not isinstance(servers, list):
                raise ConfigValidationError(f"群组 {group_id} 的服务器配置必须是数组")

            normalized_servers = []
            known_server_names = set()
            for server_index, server in enumerate(servers, start=1):
                server_label = f"群组 {group_id} 的第 {server_index} 个服务器"
                if not isinstance(server, dict):
                    raise ConfigValidationError(f"{server_label}必须是对象")

                name = cls._required_string(server.get("name"), f"{server_label}名称")
                name_key = re.sub(r"\s+", "", name)
                if name_key in known_server_names:
                    raise ConfigValidationError(f"群组 {group_id} 中的服务器名称 {name} 重复")
                known_server_names.add(name_key)

                normalized_server = copy.deepcopy(server)
                normalized_server["name"] = name
                normalized_server["address"] = cls._server_address(
                    server.get("address"), f"服务器 {name} 的地址"
                )
                normalized_server["hh_channel_id"] = cls._string(
                    server.get("hh_channel_id", ""),
                    f"服务器 {name} 的黑盒频道 ID",
                )
                normalized_server["rcon_password"] = cls._string(
                    server.get("rcon_password", ""), f"服务器 {name} 的 RCON 密码"
                )
                normalized_servers.append(normalized_server)

            normalized_group["servers"] = normalized_servers
            normalized_groups.append(normalized_group)

        normalized["group_configs"] = normalized_groups
        try:
            json.dumps(normalized, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ConfigValidationError("配置包含无法写入 JSON 的值") from exc
        return normalized

    @staticmethod
    def _string(value: Any, label: str) -> str:
        if value is None:
            return ""
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            raise ConfigValidationError(f"{label}必须是文本")
        return str(value).strip()

    @classmethod
    def _required_string(cls, value: Any, label: str) -> str:
        result = cls._string(value, label)
        if not result:
            raise ConfigValidationError(f"{label}不能为空")
        return result

    @classmethod
    def _identifier(cls, value: Any, label: str) -> str:
        result = cls._required_string(value, label)
        if any(character.isspace() for character in result):
            raise ConfigValidationError(f"{label}不能包含空格")
        return result

    @classmethod
    def _identifier_list(cls, value: Any, label: str):
        if not isinstance(value, list):
            raise ConfigValidationError(f"{label}必须是数组")
        result = []
        seen = set()
        for item in value:
            identifier = cls._identifier(item, label)
            if identifier not in seen:
                seen.add(identifier)
                result.append(identifier)
        return result

    @staticmethod
    def _boolean(value: Any, label: str) -> bool:
        if not isinstance(value, bool):
            raise ConfigValidationError(f"{label}必须是布尔值")
        return value

    @classmethod
    def _optional_url(cls, value: Any, label: str) -> str:
        result = cls._string(value, label)
        if not result:
            return ""
        parsed = urlparse(result)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConfigValidationError(f"{label}必须是有效的 HTTP/HTTPS URL")
        return result.rstrip("/")

    @classmethod
    def _server_address(cls, value: Any, label: str) -> str:
        result = cls._required_string(value, label)
        if any(character.isspace() for character in result) or result.count(":") > 1:
            raise ConfigValidationError(f"{label}格式应为 host 或 host:port")

        if ":" in result:
            host, port_text = result.rsplit(":", 1)
            if not host or not port_text.isdigit():
                raise ConfigValidationError(f"{label}格式应为 host:port")
            port = int(port_text)
            if not 1 <= port <= 65535:
                raise ConfigValidationError(f"{label}端口必须在 1 到 65535 之间")
        return result

    def get_group_config(self, group_id: str) -> Optional[Dict[str, Any]]:
        """根据群号获取配置。"""
        with self._lock:
            group_configs = self.config.get("group_configs", [])
            for conf in group_configs:
                if str(conf.get("group_id")) == str(group_id):
                    return copy.deepcopy(conf)
        return None

    def get_connect_base_url(self) -> str:
        with self._lock:
            return self.config.get("connectBaseUrl", "")

    def get_map_name_url(self) -> str:
        with self._lock:
            return self.config.get("mapNameUrl", "")

    def get_safe_mode(self) -> bool:
        with self._lock:
            return bool(self.config.get("safeMode", False))

    def get_hh_bot_id(self) -> str:
        with self._lock:
            return str(self.config.get("hh_bot_id", "") or "")

    def get_hh_bot_token(self) -> str:
        with self._lock:
            return str(self.config.get("hh_bot_token", "") or "")
