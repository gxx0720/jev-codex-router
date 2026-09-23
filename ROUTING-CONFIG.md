# Jev 路由配置

本机的 Jev 路由策略由 `D:\JevRouter\routing-config.json` 控制。日常调整模型、reasoning effort 或回退策略时，只需修改这个 JSON 文件，不需要改 Python 源码。

当前策略将 DeepSeek 低/高档和 GPT-6 Sol/Luna 支持的 reasoning effort 展开为独立候选：

- `deepseek/deepseek-v4-flash-vision-exp` + `low`（下限）
- `deepseek/deepseek-v4-flash-vision-exp` + `high`（该模型不支持 `medium`）
- `gpt-6-luna` + `low` / `medium` / `high` / `xhigh` / `max`
- `gpt-6-sol` + `low` / `medium` / `high` / `xhigh` / `max`

GPT-5.6 和 GPT-6 Astra 当前不在候选列表中。Jev 会在以上十二个 model/effort 组合中选择。`fallback`、`off_route` 和 `shadow_route` 当前都固定为 `gpt-6-sol` + `medium`。`codex_dry_enabled` 为 `false`，因此不会触发旧的 codex-dry 外部回退。

`weekly_quota_guard` 是周额度保护：当 Codex 七天窗口剩余 `<= 1%` 时，或服务无法读取周额度时，绕过 GPT 路由并固定使用 `deepseek/deepseek-v4-flash-vision-exp` + `low`。服务在每次模型调用前通过 Codex app-server 读取额度；剩余比例回到 1% 以上后自动恢复普通路由。日志字段 `weekly_remaining_percent` 和 `weekly_quota_guard` 可用于确认状态。可修改 `remaining_percent_at_or_below` 调整阈值。

图片、音频、视频或文件输入会标记为多模态请求，Jev 的该次候选中会排除 DeepSeek，避免把媒体内容发送给当前按纯文本处理的 DeepSeek 路由。若周额度保护正在强制 DeepSeek（包括额度读取失败），服务会在转发前明确拒绝该多模态请求，不会绕过保护改用 GPT，也不会把媒体发给 DeepSeek；等额度恢复且可读后重试。

`sticky_turn_enabled` 控制路由频率：

- `false`（默认）：每个 user/tool/continuation 调用都重新让 Jev 选择，允许同一 turn 内灵活切换模型。
- `true`：一条用户消息只选择一次，后续工具步骤沿用同一模型和 effort。

修改配置后，在 PowerShell 中重启 Jev：

```powershell
Stop-ScheduledTask -TaskName "Jev Codex Router"
while ((Get-ScheduledTask -TaskName "Jev Codex Router").State -ne "Ready") { Start-Sleep -Milliseconds 300 }
Start-ScheduledTask -TaskName "Jev Codex Router"
```

检查服务：

```powershell
Invoke-RestMethod http://127.0.0.1:4319/health
```

如果 JSON 格式错误、字段缺失、reasoning effort 不合法，或配置了重复路由，Jev 会拒绝启动，不会静默选择一个更强的模型。启动错误记录在 `D:\JevRouter\logs\jev-server.err.log`。计划任务设置为 `IgnoreNew`，停止后必须等任务状态回到 `Ready` 再启动。

快速暂停 Jev 的动态判断时，可以创建下面的标记文件；请求会固定使用 `off_route`：

```powershell
New-Item -ItemType File -Path "C:\Users\gxx_q\.codex\codex-router\jev-router.off"
```

恢复动态判断时删除该文件：

```powershell
[System.IO.File]::Delete("C:\Users\gxx_q\.codex\codex-router\jev-router.off")
```

这里的“暂停 Jev 动态判断”不会停止 Codex Router，也不会让 Codex 无法使用；它只是让 `jev/auto` 固定走配置中的 `off_route`。
