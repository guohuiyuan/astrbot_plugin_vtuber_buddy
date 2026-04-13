# VTuber Buddy

一个基于 AstrBot 的紧凑型 Live2D 陪伴插件。

当前版本提供：

- 由 AstrBot 插件直接拉起的本地 Web 应用
- 紧凑单页舞台，主视图以 Live2D 角色为核心
- 浮动设置面板
- 极简养成状态机：饱食度、心情值、好感度
- 触摸、投喂、聊天三种核心交互
- 记忆雏形：会记住用户透露的稳定偏好或事实
- 完整走 AstrBot 主链路的大模型请求
- 内置 EchoBot 示例 Live2D 模型，并支持动作、表情、视线跟随

## 使用

1. 在 AstrBot 中启用插件。
2. 发送 `/buddy` 获取本地入口地址。
3. 浏览器打开后即可开始互动。
4. 默认可直接使用插件内置 Live2D 模型，也可以在设置面板里填写外部模型 URL。

## 配置

插件管理页可配置：

- `web_host`
- `web_port`
- `chat_provider_id`
- `inherit_default_persona`
- `history_limit`
- `memory_limit`
- `satiety_decay_per_hour`
- `mood_decay_per_hour`
- `request_timeout_seconds`

## 备注

- 如果 AstrBot 没有可用的大模型链路，页面仍可打开，但聊天会回退到兜底提示。
- 当前 Web 端仍然是 MVP，后续可以继续向桌宠窗口形态演进。
