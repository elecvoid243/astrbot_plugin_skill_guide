# astrbot_plugin_skill_guide 设计文档

- 日期: 2026-08-15
- 作者: elecvoid243
- 状态: 已获用户批准（brainstorming 流程）
- 仓库: `F:\github\astrbot_plugin_skill_guide`（独立仓库，与 AstrBot 主仓库分离）

## 1. 背景与目标

AstrBot Dashboard 的 ChatInput 已有 `command-suggestion` 斜杠命令提示。用户希望新增能力：
**在当前会话中手动"加载"一个 skill** —— 通过前端 UI 列出当前会话生效的 skill，用户点击后，
插件将一段引导提示词注入到该会话**下一次** LLM 请求的 `extra_user_content_parts`
（即用户所称的 extra_content）中，鼓励 LLM 使用该 skill。

约束（用户明确指定）：

- 不做 builtin star 修改，实现为一个独立插件
- 仅做引导注入（nudge），**不修改** persona、**不修改** skill 的全局 active 状态
- 注入语义：**一次性**（仅下一次 LLM 请求，之后自动清除）
- 参考 `astrbot_plugin_livingmemory`（on_llm_request 钩子注入）与
  `astrbot_plugin_spcode_toolkit`（webapi 注册模式）的实现方式
- 前端 UI 由用户自行实现；本插件提供 webapi 契约并写入 README
- 插件作为独立 git 仓库开发，不改动 AstrBot 主仓库

## 2. 关键机制调研结论（代码依据）

### 2.1 当前会话活跃 skill 的判定

`astrbot/core/astr_main_agent.py::_ensure_persona_and_skills` 中，真正注入 LLM 请求的
skill 由以下步骤决定（本插件需逐行复刻）：

1. `SkillManager().list_skills(active_only=True, runtime=runtime)` — 全局 active 的 skill
   （runtime 来自 `provider_settings.computer_use_runtime`，默认 `"local"`）
2. `_filter_skills_for_current_config(skills, cfg)` — 按 `cfg.plugin_set` 过滤插件类 skill
   （`["*"]` 或缺失 = 全部放行；列表 = 仅允许列表中的插件；插件未激活/被卸载则剔除）
3. `persona_manager.resolve_selected_persona(umo, conversation_persona_id, platform_name, provider_settings)`
   解析当前会话生效人格 `persona`
4. 按 `persona["skills"]` 白名单过滤：

   | persona["skills"] | 效果 |
   |---|---|
   | `None`（未设置） | 全部活跃 skill 生效 |
   | `[]`（空列表） | 无任何 skill 生效 |
   | `["a","b"]` | 仅列表中命名的 skill 生效 |

5. 本地 runtime 下追加 workspace skills（`<workspace>/skills/*`，且 persona.skills != `[]`）

### 2.2 注入机制

- `ProviderRequest.extra_user_content_parts: list[ContentPart]`（`astrbot/core/provider/entities.py`）
  官方注释："额外的用户消息内容部分列表，用于在用户消息后添加额外的内容块（如系统提醒、指令等）"
  —— 即用户所指的 extra_content
- 文本块: `TextPart(text=...)`（`astrbot/core/agent/message.py`，未在 `astrbot.api` 导出，
  需直接 import core）
- `TextPart.mark_as_temp()` 标记 `_no_save`，仅面向 provider、不落会话历史
- `@filter.on_llm_request()` 钩子在每次 LLM 请求组装前触发（`(event, req)`），
  直接修改 `req` 即可生效；spcode / livingmemory 均采用此模式

### 2.3 WebAPI 注册

- `plugin.context.register_web_api(route, view_handler, methods, desc)`
- 前端通过 `pluginExtensionApi.get('skill-guide/active', {params:{umo}})` 调用
  → `/api/v1/plugins/extensions/skill-guide/active`；后端 `_match_registered_web_api`
  按完整路径匹配所有插件注册的路由，因此路由必须带唯一前缀 `/skill-guide/*` 防冲突
- handler 签名：`async def handle(plugin, *, umo=None, body=None)`，从
  `astrbot.api.web.request`（Quart 风格 proxy）读取 query/body；
  返回 `{"status": "ok", "data": {...}}` 信封（参考 spcode `tools/webapi/_wrap`）

## 3. 设计决策（已确认）

| # | 决策 | 选择 | 理由 |
|---|---|---|---|
| D1 | 注入语义 | **一次性**（queue → 首次请求 drain） | 用户选择；贴合"下次请求"表述 |
| D2 | 前端列表范围 | 仅会话活跃 skill（webapi 1 数据） | 非活跃 skill 注入引导无意义（LLM 无其指令） |
| D3 | 引导文本语言 | 英文 | 对齐 `build_skills_prompt` 风格 |
| D4 | 插件名 | `astrbot_plugin_skill_guide` | 命名规范 |
| D5 | 路由前缀 | `/skill-guide/*` | 全局路由匹配防冲突 |
| D6 | 注入位置 | `extra_user_content_parts`（TextPart） | 用户指定 extra_content；不改 system_prompt |
| D7 | 不改全局状态 | 不调 `set_skill_active`、不改 persona | 用户约束；副作用最小 |

## 4. 架构与组件

```
astrbot_plugin_skill_guide/
├── metadata.yaml            # 插件元数据
├── main.py                  # @register Star 入口：注册 webapi + on_llm_request 钩子
├── core/
│   ├── guide_state.py       # per-umo 一次性待注入队列（dict + threading.Lock）
│   ├── skill_resolver.py    # 当前会话活跃 skill 解析（复刻 2.1 逻辑）
│   └── guidance.py          # 引导提示词模板
├── webapi.py                # register_routes(plugin)：3 个端点
├── docs/superpowers/specs/  # 本文档
├── README.md                # 安装 + API 契约（前端消费）
├── requirements.txt         # 空（无第三方依赖）
└── tests/                   # guide_state / guidance / skill_resolver 单测
```

- `main.py` 只做编排：实例化 state/resolver → `register_routes()` → 暴露钩子
- 钩子、webapi handler 均委托 core 模块，保持薄壳（参考 spcode main.py 拆分模式）

### 4.1 core/guide_state.py

```python
class GuideState:
    """per-umo 一次性待注入队列。"""
    def __init__(self) -> None:
        self._pending: dict[str, list[str]] = {}   # umo -> [skill_name,...]
        self._lock = threading.Lock()

    def queue(self, umo: str, skill_name: str) -> bool:
        """入队（去重）。返回 True=新增, False=已存在。"""
    def drain(self, umo: str) -> list[str]:
        """弹出并清空该 umo 的全部待注入 skill（一次性语义核心）。"""
    def clear(self, umo: str) -> list[str]:
        """仅清空不消费（返回被清除列表，供 /clear 端点）。"""
    def peek(self, umo: str) -> list[str]:
        """只读查看。"""
    def clear_all(self) -> None:  # terminate() 调用
```

### 4.2 core/skill_resolver.py

```python
async def resolve_active_skills(plugin, umo: str) -> list[SkillInfo]:
    """复刻 astr_main_agent._ensure_persona_and_skills 的 skill 判定（不含 workspace）。"""
```

步骤（对应 2.1）：

1. 读配置：`plugin.context.astrbot_config_mgr`（provider_settings / computer_use_runtime / plugin_set）
2. `SkillManager().list_skills(active_only=True, runtime=runtime)`
3. **本地复刻** `_filter_skills_for_current_config`（决策：不复用核心函数，避免 import
   整个 `astr_main_agent` 模块引入沉重依赖链；该函数约 20 行，逻辑简单，插件内实现等价版，
   同样依赖 `from astrbot.core.star.star import star_registry` 判断插件激活态，
   测试中 stub `star_registry`）
4. 取会话级 persona：`conversation_id = await context.conversation_manager.get_curr_conversation_id(umo)`；
   `conv = await context.conversation_manager.get_conversation(umo, conversation_id)`；
   `conversation_persona_id = conv.persona_id if conv else None`（`Conversation.persona_id`
   字段已确认存在于 `astrbot/core/db/po.py`）
5. `resolve_selected_persona(umo, conversation_persona_id, platform_name, provider_settings)`
   → `persona`；取不到时该函数内部回退 `provider_settings.default_personality` 与 webchat 默认人格
6. 按 `persona["skills"]` 过滤

**范围裁剪（v1）**：不含 workspace skills（webchat 会话通常无；`_get_workspace_path_for_umo`
依赖主 agent 内部逻辑，插件侧复刻成本高收益低）。在 README 注明此限制。

### 4.3 core/guidance.py

```python
def build_guidance(skill: SkillInfo) -> str:
    """英文引导模板，风格对齐 build_skills_prompt（name + description + path）。"""
```

模板：

```
[User skill request]
The user explicitly asks you to use the following skill for this request:
- **<name>**: <description>
  File: `<path>`
Read and follow its SKILL.md instructions before acting. Do not skip it.
```

### 4.4 webapi.py

`register_routes(plugin)` 注册（handler 均按 spcode `_wrap` 风格取参）：

| 方法 | 路由 | 参数 | 行为 | 返回 data |
|---|---|---|---|---|
| GET | `/skill-guide/active` | query: `umo` | 解析会话活跃 skill | `{persona:{id,name}, skills:[{name,description,path,source_type}]}` |
| POST | `/skill-guide/load` | body: `{umo, skill_name}` | 校验存在且活跃 → 入队 | `{skill_name, queued:true}` |
| POST | `/skill-guide/clear` | body: `{umo}` | 清空未消费队列 | `{cleared:[skill_name,...]}` |

错误信封：`{"status": "error", "message": "..."}`；HTTP 状态码保持 200（与 spcode 一致），
错误语义放信封内。

### 4.5 main.py 钩子

```python
@filter.on_llm_request()
async def _inject_pending_guidance(self, event, req):
    """一次性注入：drain 队列 → 每个 skill 追加一个 TextPart 到 req.extra_user_content_parts。"""
    pending = self._state.drain(event.unified_msg_origin)
    if not pending:
        return
    for skill in pending:
        req.extra_user_content_parts.append(
            TextPart(text=build_guidance(skill)).mark_as_temp()
        )
```

- `terminate()` → `self._state.clear_all()`
- 钩子内 try/except 兜底，异常仅记日志不抛出

## 5. 数据流

```
前端 UI
  │  GET /skill-guide/active?umo=xxx
  ▼
webapi → skill_resolver（SkillManager + persona 过滤）→ {persona, skills[]}
  │
  │  POST /skill-guide/load {umo, skill_name}
  ▼
webapi → 校验 → guide_state.queue(umo, name)
  │
  │  （用户下一条消息 → 主 agent → on_llm_request 钩子）
  ▼
hook → guide_state.drain(umo) → req.extra_user_content_parts += [TextPart(...)]
  │
  ▼
Provider 组装请求 → LLM 收到引导 → 优先使用该 skill
```

## 6. 边界与错误处理

| 场景 | 处理 |
|---|---|
| 缺 `umo` | `{"status":"error","message":"missing umo"}` |
| skill 不存在 | `{"status":"error","message":"skill not found"}` |
| skill 不在会话活跃列表 | `{"status":"error","message":"skill not active in this session"}`（提示前端该 skill 不可点） |
| 重复点击同一 skill | `queue()` 去重，返回 queued:true（幂等） |
| 多个 skill 排队 | 全部注入（各一个 TextPart） |
| 队列为空时钩子 | 直接 return，零开销 |
| 钩子内异常 | 记日志，不抛出，不阻断请求 |
| 插件卸载 | `terminate()` 清空 state |

## 7. 测试

- `tests/test_guide_state.py`：queue 去重 / drain 一次性（二次 drain 为空）/ clear / 多 skill / 并发安全
- `tests/test_guidance.py`：模板渲染（name/description/path 注入、空 description 兜底）
- `tests/test_skill_resolver.py`：stub SkillManager + persona 三态（None/[]/白名单）+ plugin_set 过滤
  （遵循仓库 conftest stub 惯例，不依赖真实运行时）

## 8. 前端契约（用户实现，README 同步）

1. 挂载时 `GET /skill-guide/active?umo=<当前会话umo>` 渲染列表（persona 无 skill 时为空列表）
2. 点击 skill → `POST /skill-guide/load {umo, skill_name}`，成功后 UI 提示"将在下一条消息生效"
3. 可选"撤销"按钮 → `POST /skill-guide/clear {umo}`
4. 会话切换/刷新后重新拉取 active 列表（列表反映 persona 与全局 active 的实时状态）

## 9. 范围外（v1 明确不做）

- workspace skills 解析
- 持久化队列（重启即清空 —— 一次性语义下可接受）
- 前端 UI（用户自行实现）
- 修改 persona / skill active 状态
- 非活跃 skill 的"强制加载"（需要嵌入 SKILL.md 全文，v2 再议）
