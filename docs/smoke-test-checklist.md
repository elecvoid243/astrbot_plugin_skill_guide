# Skill Guide 插件 — 部署冒烟测试清单

> 目的：首次部署（以及 AstrBot 升级后）在**真实 AstrBot 环境**中验证
> `main.py` 的 hook 与 `webapi.py` 的 `_wrap` 适配层（这两部分无法单测，依赖运行时 API）。
> 覆盖范围：`astrbot.core` 内部 API（`TextPart`、`SkillManager`、`star_registry`、`conversation_manager`、
> `persona_manager.resolve_selected_persona`），这些不属于稳定的 `astrbot.api`。

## 前置条件

- [ ] 插件目录已放入 `data/plugins/`，AstrBot 已重启，日志无加载报错
- [ ] 至少有一个全局 active 的 skill（或在当前 persona 白名单内）
- [ ] 一个可用的会话（拿到 `umo`，如 `webchat:FriendMessage:...`）

## 1. WebAPI 冒烟

### GET `/skill-guide/active`

- [ ] 带有效 `umo` → `status: ok`，`data.skills` 为非空列表，每项含
      `name` / `description`（字符串，非 null）/ `path` / `source_type`
- [ ] 缺失 `umo` → `status: error`，`message` 含 `missing umo`（HTTP 200）

### POST `/skill-guide/load`

- [ ] 有效 `{umo, skill_name}`（skill 在当前会话生效）→ `status: ok`，
      `data = {skill_name, queued: true}`
- [ ] 未知/未生效的 `skill_name` → `status: error`，`message` 含 `not found`
- [ ] 缺失 `skill_name` → `status: error`，`message` 含 `missing skill_name`
- [ ] （健壮性）发送非 dict JSON body（如 `[1]`）→ 返回错误信封，而非 500

### POST `/skill-guide/clear`

- [ ] 先 `/load` 再 `/clear` 同一 `umo` → `data.cleared` 返回被清掉的 skill 名
- [ ] 重复 `/clear` → `data.cleared` 为空数组

## 2. 注入冒烟（核心）

1. [ ] `POST /skill-guide/load` 排队 `brainstorming`（假设该 skill 生效）
2. [ ] 在同一会话发送一条普通聊天消息
3. [ ] 确认该次 LLM 请求的 `extra_user_content_parts` 中出现了引导文本
      （含 `[User skill request]`、skill 名、`SKILL.md` 路径）
4. [ ] 确认**一次性语义**：再发一条消息，`extra_user_content_parts` 不再包含引导文本
5. [ ] 确认**不落历史**：查看会话 saved history，引导文本**没有**被持久化
      （依赖 `TextPart.mark_as_temp()`，即 `_no_save` 标记）
6. [ ] 确认会话 persona / skill 全局 active 状态未被修改

## 3. 升级回归

- [ ] AstrBot 升级（`metadata.yaml` 允许范围内，`>=4.16,<5`）后，重跑以上 1/2 全部步骤
      —— 插件触碰 `astrbot.core` 内部 API，升级后必须重验

## 常见问题

- `active` 返回空列表：确认 skill 全局 active，且 persona 白名单未过滤掉
- 注入未生效：确认 `/load` 返回 `queued: true`，且发送消息的会话与 `umo` 一致
- 升级后 hook 抛错：查看插件日志 `[skill_guide] injection failed: ...`
  （hook 已保证不阻塞请求，但需根据日志修正兼容性）
