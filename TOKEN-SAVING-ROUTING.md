# Jev Codex Router 节省模型额度方案

## 目标

通过 Jev 在每个用户轮次开始时判断任务需求，动态选择合适的模型和 reasoning effort，避免所有任务都长期使用最强模型。

这套方案主要节省：

- 高端模型额度
- 高 effort 带来的推理成本
- 不必要的模型调用

它不保证原始 input token 数量下降。完整上下文仍会发送给最终执行模型，Jev 自身的判断也会消耗少量 token。

## 整体架构

```text
Codex
  ↓
Codex Router :4202
  ↓
jev/auto
  ↓
Jev Router :4319
  ├─ 将当前用户任务的摘要发送给 Jev 判断
  ├─ 选择 model + reasoning effort
  └─ 将完整的 Codex 请求转发给实际模型
       ↓
    Luna / Terra / Sol / DeepSeek
```

Codex Router 负责 provider 和模型入口；Jev Router 负责动态路由。Codex Router 的 UI 不是 Jev 策略编辑器。

## 本机目录和运行方式

项目目录：

```text
D:\JevRouter
```

主要文件：

- `server/jev_server.py`：本地 Jev 转发服务
- `server/routing_policy.py`：路由选择契约和校验
- `routing-config.json`：本机路由边界和回退策略
- `start-jev-router.ps1`：Windows 启动脚本
- `logs/jev-server.out.log`：标准输出日志
- `logs/jev-server.err.log`：错误日志

Jev 目前通过 Windows 计划任务 `Jev Codex Router` 持久运行，而不是标准 Windows Service。服务只监听本机回环地址：

```text
http://127.0.0.1:4319
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:4319/health
```

API key 从项目 `.env` 读取，密钥值不应写入日志、文档或聊天消息。代理 `127.0.0.1:7897` 只作用于 Jev 服务进程，不永久修改系统全局代理。

## 当前路由边界

当前策略由 [routing-config.json](D:\JevRouter\routing-config.json) 控制。Jev 可从以下十二个 `model + effort` 组合中选择：

```text
deepseek/deepseek-v4-flash-vision-exp : low / high
gpt-6-luna                           : low / medium / high / xhigh / max
gpt-6-sol                            : low / medium / high / xhigh / max
```

边界为：

```text
最低：DeepSeek + low
最高：GPT-6 Sol + max
```

当前固定路由：

```text
fallback    → gpt-6-sol + medium
off_route   → gpt-6-sol + medium
shadow_route→ gpt-6-sol + medium
```

GPT-5.6 和 GPT-6 Astra 均已从当前候选中移除。`codex_dry_enabled` 当前为 `false`。

## Jev 如何选择

模型强弱和 reasoning effort 是两个独立维度。Jev 不是先输出一个笼统的“低、中、高”再由本机代码机械映射，而是直接从允许的组合中选择一项：

```json
{
  "model": "gpt-6-luna",
  "effort": "high"
}
```

例如，以下都是不同的候选：

```text
GPT-6 Luna:high
GPT-6 Sol:low
GPT-6 Sol:medium
```

增加 effort 不等于自动获得更强模型的能力；较强模型使用低 effort，也不等价于较弱模型使用高 effort。

Jev 的结果会经过本机校验。只有配置文件中存在的组合才能被执行；无效响应、Jev 请求失败或没有有效任务时，会进入 `fallback`。

## 每步路由的生命周期

当前默认采用灵活的 per-call routing：

```text
新的用户消息
  ↓
Jev 判断当前步骤的 model + effort
  ↓
执行并取得工具结果
  ↓
下一次模型调用根据新步骤重新判断
```

因此，同一个长任务内部可以在不同工具步骤之间切换模型，避免首次选到的高成本模型贯穿整个任务。将 `routing-config.json` 中的 `sticky_turn_enabled` 改为 `true`，可选择整轮固定路由。

## Codex 模型选择器中的 low / medium / high

选择 `Jev Codex Router` 后，Codex UI 仍然要求选择一个 effort。这是 Codex 通用模型目录的界面要求。

对于 `jev/auto`，该 UI 选择不会限制最终路由。Jev 服务会覆盖请求中的 `reasoning.effort`：

```text
UI 选择的 effort
  ↓
发送到 Jev Router
  ↓
Jev 重新选择实际 model + effort
  ↓
以 Jev 的选择执行
```

因此 UI 中保持 `medium` 即可。真正的模型边界由 `routing-config.json` 决定。

## 查看实际模型选择

### 对话内标签

启用以下标记文件后，每条用户消息后的可见回复会显示实际路由：

```text
C:\Users\gxx_q\.codex\codex-router\jev-router.signature
```

示例：

```text
🧠 sol · thinking: medium
🌍 terra · thinking: high
⚡ luna · thinking: low
```

### 实时查看日志

在 PowerShell 中运行：

```powershell
Get-Content "C:\Users\gxx_q\.codex\codex-router\sessions\<session-hash>\jev-router-live.jsonl" -Wait |
ForEach-Object {
    try {
        $r = $_ | ConvertFrom-Json
        "{0} | {1,-9} | {2}:{3} | sticky={4} | gate={5}" -f `
            $r.at, $r.step, $r.model, $r.effort, $r.sticky, $r.gate
    } catch {}
}
```

关键字段：

- `step: user_turn`：新用户轮次，Jev 刚做出选择
- `step: tool_step`：工具调用后的继续执行
- `sticky_enabled: false`：当前配置为每步灵活路由
- `sticky: false`：本次调用经过了新的 Jev 判断
- `sticky: true`：已开启 sticky 模式，本次沿用本轮路由
- `model`：实际执行模型
- `effort`：实际 reasoning effort

日志现在按 Codex 会话分目录保存。`<session-hash>` 是请求中
`prompt_cache_key` 的不可逆短哈希，不会把原始会话标识写入磁盘：

```text
C:\Users\gxx_q\.codex\codex-router\sessions\<session-hash>\jev-router-live.jsonl
```

同一目录还会保存开启 debug 时的 `jev-router-debug.jsonl` 和
`jev-router-debug-stream.log`。未携带会话标识的请求会按任务内容哈希归档。
- `gate`：正常应用、回退或关闭动态路由等路径

## 暂停动态路由

创建标记文件后，`jev/auto` 会固定走 `off_route`，不会调用 Jev 做动态判断：

```powershell
New-Item -ItemType File -Path "C:\Users\gxx_q\.codex\codex-router\jev-router.off"
```

删除标记即可恢复：

```powershell
[System.IO.File]::Delete("C:\Users\gxx_q\.codex\codex-router\jev-router.off")
```

这不会停止 Codex Router，也不会让 Codex 失效；它只会把 `jev/auto` 固定到配置中的 `off_route`（当前是 `gpt-6-sol + medium`）。

## 修改策略后的操作

编辑：

```text
D:\JevRouter\routing-config.json
```

修改后重启计划任务：

```powershell
Stop-ScheduledTask -TaskName "Jev Codex Router"
Start-ScheduledTask -TaskName "Jev Codex Router"
```

然后检查：

```powershell
Invoke-RestMethod http://127.0.0.1:4319/health
```

JSON 错误、字段缺失、非法 effort 或重复路由会阻止 Jev 启动，不会静默切换到更强模型。错误详情写入：

```text
D:\JevRouter\logs\jev-server.err.log
```
