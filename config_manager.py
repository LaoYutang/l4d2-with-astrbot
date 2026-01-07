import json
import os
from typing import List, Dict, Any, Optional

class ConfigManager:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        if not os.path.exists(self.config_path):
            # 创建默认配置
            default_config = {
                "connectBaseUrl": "", # 可选，一键连接的基础URL，例如 https://steam-connect.laoyutang.cn
                "mapNameUrl": "", # 可选，获取地图真名API，例如 https://l4d2-maps.laoyutang.cn
                "group_configs": [
                    {
                        "group_id": 12345678,
                        "admin_users": [], # 管理员QQ列表，只有列表中的用户可以使用重启指令
                        "servers": [
                            {
                                "name": "示例服务器", 
                                "address": "127.0.0.1:27015",
                                "rcon_password": "your_rcon_password_here" # 可选，用于重启服务器
                            }
                        ]
                    }
                ]
            }
            self._save_config(default_config)
            return default_config
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            # 如果加载失败，返回空配置
            return {}

    def _save_config(self, config: Dict[str, Any]):
        # 确保目录存在
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

    def get_group_config(self, group_id: str) -> Optional[Dict[str, Any]]:
        """根据群号获取配置"""
        group_configs = self.config.get("group_configs", [])
        for conf in group_configs:
            if str(conf.get("group_id")) == str(group_id):
                return conf
        return None

    def get_connect_base_url(self) -> str:
        """获取全局连接基础URL"""
        return self.config.get("connectBaseUrl", "")

    def get_map_name_url(self) -> str:
        """获取地图真名API"""
        return self.config.get("mapNameUrl", "")
