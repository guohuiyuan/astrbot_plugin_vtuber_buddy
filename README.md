# VTuber Buddy

一个基于 AstrBot 的紧凑型陪伴插件。

当前版本提供：

- 独立启动的本地 Web 应用
- 单页舞台式界面，主视图只保留 Live2D 区域、状态条、气泡和输入框
- 浮动设置面板
- 极简养成状态机：饱食度、心情值、好感度
- 触摸、喂食、聊天三种核心交互
- 记忆雏形：会记住用户透露的稳定偏好或事实
- 大模型调用直接复用 AstrBot 已配置的聊天 Provider

## 使用

1. 在 AstrBot 中启用插件。
2. 发送 `/buddy` 获取本地入口地址。
3. 浏览器打开后即可开始互动。
4. 如果你有自己的 Live2D 模型，可以在设置面板里填入模型 JSON URL。

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

## 备注

- 没有配置 AstrBot 聊天模型时，页面仍可打开，但会退化为规则回复。
- 当前 Web 端主要为 MVP，后续可以继续向桌宠窗口形态演进。
