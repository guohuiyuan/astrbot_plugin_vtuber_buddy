# VTuber Buddy

一个基于 AstrBot 的轻量级 Live2D 陪伴插件，当前版本已经打通从浏览器交互到 AstrBot 主链路对话的完整闭环。

## 当前已实现的核心能力

### 1) 大模型对话能力（已接入 AstrBot 主链路）

- Web 端聊天请求会进入 AstrBot 主事件链路，再回传到 Buddy 页面。
- 支持指定 `chat_provider_id` 固定模型供应商，也可留空跟随当前会话。
- 对话输出使用结构化约定（`reply/emotion/motion/memory`），可以同步驱动角色情绪与动作。
- 当主链路异常时会返回兜底回复，保证页面可继续使用。

### 2) Live2D 基础展示能力（可用）

- 内置 Live2D 模型可直接加载展示。
- 支持工作区模型发现与切换，也支持填写外部模型 URL。
- 支持基础动作、表情映射与鼠标跟随。
- 本地 Web 舞台可正常渲染角色，并随聊天状态更新表现。

### 3) 属性与养成功能（基础可玩）

目前有一套可运行的轻量状态机，包含：

- 等级 / 经验 / 金币
- 饱食度 / 清洁度
- 心情 / 精力 / 健康 / 好感 / 病症
- 工作状态（打工中、剩余时间、奖励）

已实现交互行为：

- 聊天：消耗部分状态并增长关系/经验
- 投喂：恢复饱食并改善状态
- 清洁：恢复清洁并降低病症风险
- 触摸：按部位触发不同反馈与数值变化
- 打工：按时长产出金币和成长，期间状态会受影响

同时支持离线衰减与恢复逻辑（按小时结算），让状态变化更连续。

### 4) 记忆功能（简版长期记忆）

- 支持从用户消息和模型返回中抽取可记忆事实。
- 当前优先覆盖偏好、身份信息、习惯、关系、计划、待办等类型。
- 聊天时会按相关性召回少量长期记忆注入提示词，增强上下文连续性。
- 记忆和会话数据持久化到 SQLite，本地可持续保存。

## 快速使用

1. 在 AstrBot 中启用插件。
2. 发送 `/buddy` 获取本地访问地址。
3. 浏览器打开地址后即可开始互动。
4. 发送 `/buddy_status` 可查看服务状态、地址与当前链路信息。

## 代码架构

### 分层结构

- 插件入口层：负责 AstrBot 生命周期、命令注册、主链路事件挂钩。
- 会话服务层：负责状态机、属性结算、互动行为、Prompt 构建。
- 记忆与持久化层：负责长期记忆抽取/召回，以及 SQLite 持久化。
- Live2D 能力层：负责模型发现、元数据修补、资源映射和前端配置下发。
- Web 接口层：提供本地页面和 REST API，把浏览器动作转成服务调用。
- 前端交互层：负责舞台渲染、Live2D 驱动、状态面板与操作按钮。

### 核心模块说明

- `main.py`
	- 插件总入口，组装 `BuddyConversationService` / `BuddyWebServer` / `AstrBotMainChainBackend`。
	- 注册 `/buddy` 与 `/buddy_status` 指令。
	- 通过 `on_llm_request` / `on_llm_response` 对 Buddy 会话进行请求装饰与结构化回包处理。

- `vtuber_buddy/service.py`
	- 核心业务中枢。
	- 负责 `chat/feed/clean/work/touch/settings` 六类动作。
	- 维护属性衰减、升级、工作结算、状态提示、对话历史与短期记忆。

- `vtuber_buddy/memory_service.py`
	- 长期记忆路由器。
	- 从用户消息与 LLM memory 字段提取候选事实，分类写入并在聊天时按相关性召回。

- `vtuber_buddy/store.py`
	- SQLite 存储层。
	- 持久化 session（设置、状态、历史、短期记忆）与 long-term memory。

- `vtuber_buddy/live2d_service.py`
	- Live2D 配置生成与模型 JSON 修补。
	- 支持内置模型、工作区模型和外部 URL 模型。

- `vtuber_buddy/web.py`
	- 本地 aiohttp 服务。
	- 提供 `/api/state`、`/api/chat`、`/api/feed`、`/api/clean`、`/api/work`、`/api/touch`、`/api/settings`、`/api/live2d/*`。

- `vtuber_buddy/static/app.js`
	- 前端主逻辑。
	- 负责 API 通信、状态渲染、设置面板、Live2D 运行时挂载、动作/表情同步。

### 一次聊天请求链路

1. 前端调用 `/api/chat`。
2. `web.py` 转发到 `service.py::chat`。
3. `service.py` 先做状态结算与记忆召回，再通过 `bridge.py` 提交 AstrBot 主链路请求。
4. `main.py` 在主链路请求/响应阶段进行 Buddy 相关 prompt 注入和结构化结果提取。
5. `service.py` 根据回复更新情绪、动作、属性、历史和记忆，并持久化到 SQLite。
6. Web API 返回新状态，前端据此刷新 Live2D 与面板。

### 数据与资源位置

- 会话与记忆数据库：`AstrBot 插件数据目录/astrbot_plugin_vtuber_buddy/buddy_state.sqlite3`
- 工作区模型目录：`AstrBot 插件数据目录/astrbot_plugin_vtuber_buddy/live2d_models`
- 内置模型目录：`vtuber_buddy/builtin_live2d`

## 配置说明

可在插件配置中调整以下参数：

### 网络与链路

- `web_host`（默认：`127.0.0.1`）
	- 本地 Web 服务绑定地址。
	- 只本机访问建议保持默认；局域网调试可改为 `0.0.0.0`。

- `web_port`（默认：`6230`）
	- 本地 Web 服务端口。
	- 端口冲突时改为未占用端口。

- `chat_provider_id`（默认：空）
	- 指定 Buddy 固定使用的 AstrBot provider。
	- 留空时跟随 AstrBot 当前会话链路。

- `request_timeout_seconds`（默认：`60`）
	- Web 请求等待主链路回包的最大时长。
	- 模型较慢时可适当提高。

- `inherit_default_persona`（默认：`true`）
	- 兼容保留项。
	- 主链路模式下 Buddy 本身已复用 AstrBot 当前会话人格与装饰。

### 会话与记忆

- `history_limit`（默认：`10`）
	- 会话历史轮次基准上限（内部按双向消息折算后裁剪）。

- `memory_limit`（默认：`12`）
	- 短期记忆（`session.memories`）保留条数。

- `long_term_memory_limit`（默认：`40`）
	- 每个会话可保留的长期记忆总条数（SQLite）。

- `memory_recall_limit`（默认：`4`）
	- 每次聊天注入 Prompt 的长期记忆条数。

- `memory_panel_limit`（默认：`8`）
	- 状态接口返回给前端展示的长期记忆条数。

### 属性系统与成长节奏

- `satiety_decay_per_hour`（默认：`150`）
	- 饱食度每小时衰减。

- `cleanliness_decay_per_hour`（默认：`130`）
	- 清洁度每小时衰减。

- `mood_decay_per_hour`（默认：`18`）
	- 心情每小时基础衰减。

- `energy_recovery_per_hour`（默认：`90`）
	- 非工作状态下每小时精力恢复。

- `growth_exp_per_hour`（默认：`100`）
	- 离线成长基础经验增量。

- `affection_decay_per_hour`（默认：`2`）
	- 长时间不互动时的好感衰减速度。

- `work_duration_minutes`（默认：`45`）
	- 每次打工持续时长，影响结算节奏。

### 建议调参

- 想让养成节奏更轻松：降低 `satiety_decay_per_hour`、`cleanliness_decay_per_hour`。
- 想让互动反馈更快：提高 `growth_exp_per_hour`，同时适度提高 `energy_recovery_per_hour`。
- 想让记忆更“稳”：提高 `long_term_memory_limit`，并将 `memory_recall_limit` 控制在 4~8 之间。

## 当前定位

这个版本的重点是验证「对话 + Live2D 展示 + 属性系统 + 记忆」四条主链路已可稳定协同。整体属于可运行 MVP，适合继续迭代 UI 细节、互动内容和更强的记忆策略。
