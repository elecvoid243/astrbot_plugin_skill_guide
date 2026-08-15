`astrbot_plugin_skill_guide` 是一个独立部署的 AstrBot 插件，提供"手动加载 skill"能力：

- **WebAPI**（供 Dashboard 前端调用）：`GET /skill-guide/active`（当前会话生效的 skill 列表）、
  `POST /skill-guide/load`（排队一次性引导注入）、`POST /skill-guide/clear`（清空队列）
- **注入机制**：用户点击 skill 后，插件将一段英文引导提示词注入到该会话**下一次**
  LLM 请求的 `req.extra_user_content_parts`（`TextPart(text=...).mark_as_temp()`），鼓励 LLM 使用该 skill
- **一次性语义**：per-umo 队列在首次 `on_llm_request` 钩子触发时 drain（消费），之后不再注入

核心设计决策（详见 `docs/superpowers/specs/2026-08-15-skill-guide-design.md`，修改前必读）：

- **只注入引导，绝不修改** persona、`SkillManager` 的 active 状态、`req.system_prompt`
- 路由统一 `/skill-guide/*` 前缀（AstrBot 全局按路径匹配插件 webapi，防冲突）
- 响应信封：`{"status": "ok", "data": {...}}` / `{"status": "error", "message": "..."}`，HTTP 200
- skill 解析逻辑**逐行镜像** `astr_main_agent._ensure_persona_and_skills`（全局 active → `plugin_set` 过滤 → persona `skills` 白名单），改动时需保持同步

仓库边界：本仓库是独立 git 仓库（`F:\github\astrbot_plugin_skill_guide`）。
**`F:\github\Astrbot` 是 AstrBot 主仓库，仅作只读参考，禁止修改**。插件运行时依赖
`astrbot.core` 内部符号（`TextPart` / `SkillManager` / `star_registry`），这些是懒加载的，
AstrBot 大版本升级后需按 `docs/smoke-test-checklist.md` 重跑冒烟测试。

## 构建/测试命令

```powershell
# 唯一可用的 Python 环境（Windows PowerShell 下 python 不在 PATH）
$PY = "D:\anaconda3\envs\astrbot\python.exe"

# 运行全部测试（pytest.ini 已配置 pythonpath = .，裸 pytest 亦可）
& $PY -m pytest                 # 期望: 31 passed
& $PY -m pytest tests/test_guide_state.py -v   # 聚焦单个文件

# Lint / 格式化
& $PY -m ruff check .
& $PY -m ruff format .

# 语法编译检查（main.py/webapi.py 顶层 import astrbot，单测不覆盖，用 compileall 兜底）
& $PY -m compileall main.py webapi.py core tests
```

开发依赖见 `requirements-dev.txt`（pytest、pytest-asyncio）；运行时零第三方依赖（`requirements.txt` 保持为空）。

## 代码风格指南

- Python 3.10+，`from __future__ import annotations`；公共方法带类型注解
- 注释与日志用**英文**；docstring 用 Google 风格（Args/Returns）
- **`core/` 模块禁止在模块顶层 import astrbot**（保持可独立单测）；胶水层（`main.py`/`webapi.py`）的 astrbot 依赖一律在函数体内懒加载
- 提交信息用 conventional commits（`feat:` / `fix:` / `test:` / `docs:` / `chore:`），作者署名 `elecvoid243`
- 保持模块单一职责、文件小而聚焦（参考现有 `core/` 拆分方式）

## 架构说明

```
main.py        Star 入口：@register 插件类；initialize() 注册 webapi；on_llm_request 钩子；terminate() 清队列
webapi.py      路由/信封/参数适配（_wrap）；纯 helper（build_active_payload / validate_load_skill）可单测
core/
  guide_state.py       per-umo 一次性队列（dict + threading.Lock；queue/drain/clear/peek/clear_all）
  guidance.py          build_guidance(skill) 英文引导模板（name + description + path）
  skill_resolver.py    filter_by_persona / filter_plugin_skills 纯函数 + resolve_active_skills 异步胶水
  injector.py          inject_pending(state, umo, req, *, skills_by_name) 一次性注入（drain 在函数内，防并发双注入）
tests/                 5 个测试文件，纯模块独立可测（不依赖 AstrBot 运行时）
docs/smoke-test-checklist.md   部署前冒烟清单（胶水层无单测，部署前必做）
```

**数据流**：前端 `GET /skill-guide/active?umo=` → `resolve_active_skills`（SkillManager →
plugin_set → persona 白名单）→ 前端 `POST /skill-guide/load {umo, skill_name}` → 校验后
`GuideState.queue` → 用户下一条消息触发 `on_llm_request` 钩子 → peek 守卫 → 重新解析 →
`inject_pending` drain 并逐个追加 `TextPart` 到 `req.extra_user_content_parts`。

**关键不变式**：

- 一次性：`inject_pending` 内部 drain；二次调用 no-op；队列中已不可解析的 skill 名静默丢弃（仍被消费）
- 钩子绝不阻断请求：任何异常只记日志；`event.unified_msg_origin` 读取在 try 内
- webapi 绝不 500：缺参/未知 skill 返回错误信封；POST body 非 dict 时按空 dict 处理
- 前端契约见 `README.md`（`pluginExtensionApi.get('skill-guide/active', {params:{umo}})` 等）

## 操作约定

- **重大修改先与维护者确认**：遵循 brainstorming → 设计文档（`docs/superpowers/specs/`）→
  实施计划（`docs/superpowers/plans/`）→ TDD 实施的流程，不要跳过设计直接改代码
- 新功能/修复采用 TDD：先写失败测试（RED）→ 实现（GREEN）→ 全量测试 → 提交
- **仅本地提交，禁止推送到远端、禁止发起 PR**（项目约束）；仓库当前无 remote
- `.superpowers/`（SDD 控制器 scratch）、`.codegraph/`、`__pycache__`、`.pytest_cache`、
  `.ruff_cache` 一律不提交（.gitignore 已覆盖）
- 修改 `resolve_active_skills` 前对照 `F:\github\Astrbot\astrbot\core\astr_main_agent.py`
  的 `_ensure_persona_and_skills` 核实语义（含 `filter_by_persona` 的 `None`/`[]`/白名单三态）
- 部署/升级 AstrBot 后按 `docs/smoke-test-checklist.md` 冒烟：三个端点正常 + 注入文本出现在
  `extra_user_content_parts` 且不落历史（`mark_as_temp`）
