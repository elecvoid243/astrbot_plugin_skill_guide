# astrbot_plugin_skill_guide

手动"加载"skill：前端列出当前会话生效的 skill，用户点击后，插件将一段引导提示词
注入到该会话**下一次** LLM 请求的 `extra_user_content_parts`，鼓励 LLM 使用该 skill。

- 一次性语义：注入后自动清除（下下次请求不再生效）
- 只注入引导，**不修改** persona、**不修改** skill 全局 active 状态
- 独立 webapi，供 Dashboard 前端调用（`pluginExtensionApi`）

## 安装

将本目录放入 AstrBot `data/plugins/` 后重启，或在插件商店安装。

## WebAPI 契约

| 方法 | 路径 | 参数 | 说明 |
|---|---|---|---|
| GET | `/skill-guide/active` | query `umo` | 当前会话生效的 skill 列表（含 persona） |
| POST | `/skill-guide/load` | body `{umo, skill_name}` | 排队一次性引导注入 |
| POST | `/skill-guide/clear` | body `{umo}` | 清空未消费队列 |

前端调用示例（axios，`pluginExtensionApi` 基址已配置好）：

```ts
// 获取活跃 skill
const res = await pluginExtensionApi.get('skill-guide/active', { params: { umo } });
// res.data.data = { persona: {id,name}|null, skills: [{name,description,path,source_type}] }

// 加载 skill
await pluginExtensionApi.post('skill-guide/load', { umo, skill_name: 'brainstorming' });
// res.data.data = { skill_name, queued: true }

// 撤销
await pluginExtensionApi.post('skill-guide/clear', { umo });
// res.data.data = { cleared: ['brainstorming'] }
```

错误响应统一为 `{ status: 'error', message }`（HTTP 200）。

## 前端建议

1. 会话挂载时调用 `/skill-guide/active` 渲染列表；会话切换后重新拉取
2. 点击 skill → `/skill-guide/load`，提示"将在下一条消息生效"
3. 可选"撤销"按钮 → `/skill-guide/clear`

## 限制（v1）

- 仅展示**当前会话生效**的 skill（全局 active + 人格白名单过滤结果）；
  不含 workspace skills
- 队列仅存内存，重启即清空（一次性语义下可接受）

## 开发

```bash
python -m pip install -r requirements-dev.txt   # pytest / pytest-asyncio
python -m pytest tests/ -v
```

## License

MIT
