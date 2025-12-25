# L4D2 Server Query Plugin for AstrBot

这是一个用于查询 Left 4 Dead 2 (L4D2) 服务器状态的 AstrBot 插件。

## 功能

- **查询单个服务器**: `查询 [服务器名]`
  - 显示服务器地图、人数、延迟以及详细玩家列表。
  - 支持模糊匹配（忽略空格）。
- **综合查询**: `综合查询`
  - 显示所有配置服务器的简略状态（地图、人数、延迟）。
- **获取连接地址**: `服务器列表` / `服务器地址` / `连接指令`
  - 列出所有服务器的 `connect IP:Port` 指令，方便复制。
  - **一键连接**: 如果在配置中设置了 `connectBaseUrl`，将生成可点击的 HTTP 连接链接（如使用 steam-connect 服务）。
- **重启服务器**: `重启 [服务器名]`
  - 通过 RCON 重启指定服务器。
  - **权限要求**: 仅在配置文件 `admin_users` 列表中的用户可执行。
  - **配置要求**: 需在配置文件中为该服务器设置 `rcon_password`。

## 安装

1. 将本插件文件夹放入 AstrBot 的 `data/plugins/` 目录下。
2. 安装依赖:
   ```bash
   pip install -r requirements.txt
   ```
   或者手动安装 `python-a2s` 和 `python-valve`。

## 配置

插件首次运行后，会在插件目录下生成 `config.json` 文件。请根据需要修改配置。

支持为不同的群组配置不同的服务器列表。

```json
{
    "connectBaseUrl": "https://xxxx.xxxx.xx", // 可选：配置一键连接的基础URL
    "group_configs": [
        {
            "group_id": 12345678,
            "admin_users": [123456789], // 管理员QQ列表，只有列表中的用户可以使用重启指令
            "servers": [
                {
                    "name": "主服务器",
                    "address": "127.0.0.1:27015",
                    "rcon_password": "your_rcon_password"  // 可选：配置 RCON 密码以启用重启功能
                },
                {
                    "name": "对抗服",
                    "address": "1.2.3.4:27016"
                }
            ]
        },
        {
            "group_id": 87654321,
            "servers": [
                {
                    "name": "二群服务器",
                    "address": "5.6.7.8:27015"
                }
            ]
        }
    ]
}
```

## 依赖

- `python-a2s`
- `python-valve`
