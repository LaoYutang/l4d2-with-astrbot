import json
import os
from typing import List, Dict, Any

class ConfigManager:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        if not os.path.exists(self.config_path):
            # 创建默认配置
            default_config = {
                "group_id": 12345678,
                "servers": [
                    {"name": "示例服务器", "address": "127.0.0.1:27015"}
                ]
            }
            self._save_config(default_config)
            return default_config
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            # 如果加载失败，返回空配置或默认配置，这里简单返回空字典
            return {}

    def _save_config(self, config: Dict[str, Any]):
        # 确保目录存在
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

    def get_group_id(self) -> int:
        return self.config.get("group_id", 0)

    def get_servers(self) -> List[Dict[str, str]]:
        """
        返回服务器列表，格式为 [{"name": "ServerName", "address": "IP:Port"}]
        """
        return self.config.get("servers", [])
    
    def get_server_by_name(self, name: str) -> Dict[str, str]:
        for server in self.get_servers():
            if server.get("name") == name:
                return server
        return None
