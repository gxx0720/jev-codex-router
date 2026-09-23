# Jev Codex Router

[![ci](https://github.com/gxx0720/jev-codex-router/actions/workflows/ci.yml/badge.svg)](https://github.com/gxx0720/jev-codex-router/actions/workflows/ci.yml)

**Per-turn model routing for Codex, driven by [Jev](https://docs.typesafe.ai) (TypeSafe System One).**

Jev chooses a model and thinking effort together for each model call, including
continuations after tools. Every route uses standard speed. The objective is
sufficient capability for the next decision with no unnecessary quota consumption.

**Historical simulation: ≈ −60 % vs full Astra** on 237 turns under the old
policy. This is not measured Codex quota saved, nor evidence for the current
policy — protocol and limitations in [BACKTEST.md](BACKTEST.md).
Installing with an AI agent? Hand it [AGENTS.md](AGENTS.md).

This is not a fork of any router: it plugs into an existing local
**Codex Router** installation through its official extension points
(a *generic provider* + a *curated model*), so router updates never overwrite it.

## How it works

```
Codex ──▶ Codex Router (:4202)
            ├─ native models ──────────────▶ ChatGPT backend (your plan)
            └─ "jev/auto" ─▶ LiteLLM ─▶ API forwarder
                                     │
                                     ▼
                          jev_server.py (127.0.0.1:4319)
                            ├─ compact decision state ─▶ Jev
                            │                           └─ model + effort
                            │
                            └─ canonical Codex replay + decision
                               └─▶ local caller edge (shared native session)
                                    └─▶ DeepSeek / GPT-6 Luna / GPT-6 Sol
```

- **Responses in, Responses out** — no format conversion; SSE event structure
  is preserved while the served-model label is added to assistant text and
  reasoning summaries. Tool calls and compaction behave natively.
- **Two independent projections** — Jev sees only the bounded decision state.
  The executing model receives the complete canonical replay held by Codex:
  instructions, history or compaction handoff, tool calls and tool results.
  The upstream Codex Router must therefore exempt the exact `jev/auto` route
  from conversation windowing and tool-result aging; those optimizations would
  otherwise destroy context before this server could relay it.
- **Fail-open** — any Jev error keeps the turn alive (safe fallback route).
- **Kill switch** — a sentinel file routes without Jev, instantly.
- **Weekly quota guard** — at 1% or less remaining, or when the weekly reading
  is unavailable, the active policy forces DeepSeek. The older Codex-dry mode
  is disabled by `routing-config.json`; its sentinel and 429 retry do nothing
  until that setting is deliberately enabled.
- **Decision log** — every routed turn is logged locally for calibration
  (`~/.codex/codex-router/jev-router-live.jsonl`), never published.

## Routing policy

The shared contract in `routing-config.json` gives Jev 12 explicit pairs:
DeepSeek Flash, GPT-6 Luna and GPT-6 Sol with their configured reasoning
efforts. GPT-5.6 and GPT-6 Astra are disabled in the active policy. Jev chooses a pair
in one Choice question, using capability profiles and the current request,
recent assistant intent, and the available tool result. Every pair uses standard
speed, overriding an incoming Fast setting, including retries and bypass modes.

There is no preferred model, target distribution, keyword-to-model rule,
low-confidence fallback to Sol, mechanical-step exception, or compaction pin.
A valid decision is applied unchanged even when several pairs are close. Jev's
confidence and full choice distribution are logged separately; neither is a
measured probability that the selected model will successfully finish the task.

The model descriptions are capability priors, not calibrated success rates.
The policy must be evaluated on completed tasks, corrections, tokens and quota,
not on a desired share of Luna calls or artificially high confidence. Schema
checks and synthetic routing samples establish wiring, not equal-quality savings.
A missing/invalid Jev response or a provider error still uses the separately
logged technical fail-open route (GPT-6 Sol at medium); the manual kill switch
and weekly quota guard are operational bypasses, not Jev decisions.

### Weekly quota guard and optional dry mode

The weekly quota guard is a separate earlier threshold: when the seven-day
Codex window has 1% or less remaining, Jev bypasses model selection and serves
`deepseek/deepseek-v4-flash-vision-exp` at `low`. It reads the account window
from Codex app-server before every model call. An unavailable quota read also
forces this DeepSeek route, so GPT is not selected while the weekly balance is
unknown. Normal choices resume once more than 1% remains. Configure the guard in
`routing-config.json`; `weekly_remaining_percent` and `weekly_quota_guard` in
the route log show its state.

The active `routing-config.json` sets `codex_dry_enabled` to `false`. A native
429 is therefore returned to the caller, not automatically retried on an
external model. The `jev-router.codex-dry` sentinel is also inactive. If dry
mode is explicitly enabled in a future policy, inspect the configured model
constants and test the fallback before relying on it; the current server code
points both dry targets at `deepseek/deepseek-v4.1-flash`, not GLM.

## Measuring what it served

The router logs one JSON line per decision in
`~/.codex/codex-router/jev-router-live.jsonl`. Treat it as private user data:
entries can include short prompt excerpts and should not be shared.
`server/report_routing.py` turns that log into the routing/savings report — the
table a third party can reproduce on their own machine:

```bash
python3 server/report_routing.py --days 7          # text tables (default window)
python3 server/report_routing.py --days 30 --json  # machine-readable
```

It prints the served model distribution (DeepSeek/Luna/Sol, plus any optional
dry route if enabled: turns + %), the share of turns served by the cheapest
tier, the share of turns held below the confidence gate, the gates encountered,
median latency (end-to-end and Jev's own decision time), and an estimate of the
real cost against two counterfactuals — every turn on `gpt-6-astra`, and every
turn on `gpt-5.6-sol`.

New log entries record a versioned decision and each upstream attempt's model,
effort, standard speed, terminal event and token usage when the provider reports
it. Only numeric usage counters are retained. Unknown usage is not counted as
zero, retries are retained, and reasoning tokens are already included in output.
The report estimates standard ChatGPT credits from these observed tokens against
all-Sol and all-Astra counterfactuals. External fallback calls are excluded from
that comparison. These are published-rate estimates, not observed account debits;
counterfactual token volumes and task quality have not been experimentally measured.

Historical entries without usage keep a separate fixed-volume API-rate proxy.
Their logged Fast speed retains its surcharge instead of being repriced by the
new policy. The old backtest is clearly labelled as a simulation. Current replay
scripts share the live decision contract and reject a cache from another policy.

Routing is flexible per call by default: user turns, tool steps, retries and
post-compaction calls each receive a fresh Jev decision, so a long task can move
between models as its work changes. Set `sticky_turn_enabled` to `true` in
`routing-config.json` to opt into one decision per turn; reused entries then
carry `sticky: true`. The compact projection sent to Jev (task, signals, tool
digest) is judgement input only: it is never reused as an execution prompt. The
executing model always receives the caller's canonical request, with only the
selected model, reasoning effort, standard service tier and required streaming
flag applied to the relay.

## Ask surface (`POST /ask`)

The server also answers typed questions directly, for local callers that bring
their own question set. The `jev-browser-choice` skill is the first one: it
turns an in-app-browser accessibility dump into one Jev `choice` question and
acts only on the validated element index, so the page never enters the model's
context.

```sh
curl -s http://127.0.0.1:4319/ask -X POST -H 'Content-Type: application/json' \
  -d '{"state":{"goal":"open the docs"},"questions":{"next":{"type":"choice","instructions":"Which element advances the goal?","criteria":{"e5":"link Documentation"}}}}'
# → {"model":"jev-1.13.0","answers":{"next":{...}},"usage":{...},"ms":612}
```

Validation is the whole contract: a JSON-serialisable `state` under 120k chars,
at most 40 questions, each a `noul`, `choice` or `score` with its instructions
and criteria. The caller's state is never logged. `502` surfaces an upstream Jev
failure — `402` means the TypeSafe account is out of credits — and `503` means
no key is configured.

## Repository layout

```
BACKTEST.md  Savings backtest — protocol, tables, limitations (the "proof")
AGENTS.md    Autonomous install & operations playbook (for AI agents)
poc/         Tiering POC, shadow replay, and the backtest tool
server/      The live server + service install (this is what runs)
hook/        Explored alternative (LiteLLM callback tap) — kept for reference
```

## Quickstart

Prerequisites: **Codex App or Codex CLI must already be installed** on the same
macOS/Linux computer; this project does not install Codex. Also required are
Git, Node.js 22.19+, `uv` (or Python 3.10+ with `venv`), Python 3.11+ for Jev,
and a TypeSafe API key. The agent playbook checks these and guides the user
through installing Codex Router if needed; it never silently installs missing
system runtimes or takes over an unknown router.

For a guided agent installation, open this repository in Codex and ask it to
“Follow [AGENTS.md](AGENTS.md) to install Jev Codex Router on this machine.” The
playbook installs the maintained [Codex Router](https://github.com/duolahypercho/codex-router)
CLI-only build when needed, connects the local Jev service, validates the
catalog, and optionally installs a per-user launchd/systemd service. You must
complete Codex login and explicitly approve sharing its ChatGPT session with
local router clients. Never paste API keys into chat; configure the TypeSafe
key in `~/.hermes/.env` or `~/.jev.env`.

The agent can check the installation without inference using
`python3 server/verify_install.py`. A complete end-to-end check needs an
explicit `python3 server/verify_install.py --live` run, which makes one real
request and may consume quota/credits. Then fully quit and reopen Codex,
create a new task, and select the Jev route. For manual operation and
troubleshooting see [server/INSTALL.md](server/INSTALL.md).

## Operations

| Action | Command |
|---|---|
| Watch decisions | `tail -f "${CODEX_HOME:-$HOME/.codex}/codex-router/jev-router-live.jsonl"` |
| See the picked model in the thread | every reasoning summary part carries the full model family tag, e.g. ` · 🧠 GPT-6 Sol:low · ` or ` · ⚡ GPT-6 Luna:low · ` |
| Show the model and thinking above every assistant message | On by default: a leading `**🧠 GPT-6 Sol · thinking: high**` appears from the first text fragment, including commentary and unphased replies. `touch ~/.codex/codex-router/jev-router.signature.off` to hide it; remove that file to show it again. The old `jev-router.signature` file is no longer needed. |
| Shadow mode (decide + log, serve configured shadow route) | `touch ~/.codex/codex-router/jev-router.shadow` |
| Debug capture (shapes + raw streams) | `touch ~/.codex/codex-router/jev-router.debug` |
| Kill switch (no Jev → configured off route) | `touch ~/.codex/codex-router/jev-router.off` (delete the file to re-enable) |
| Optional Codex-dry mode | Disabled by the current `routing-config.json`; its sentinel has no effect until enabled |
| Disable the Jev provider | `<router>/bin/model-router codex providers disable jev` |
| Revoke native sharing | `<router>/bin/model-router codex chatgpt-session disable` |
| Service status | `launchctl print gui/$(id -u)/com.thibaultsaintjean.jev-router` |

**After a Codex Router update**, verify nothing was lost:

```bash
<router>/bin/model-router codex providers        # Jev should be SHOW and ready
<router>/bin/model-router codex doctor
codex debug models                              # Jev route should be listed
curl -s http://127.0.0.1:4319/health
```

## Notes & quirks

- The router's local edge requires `stream: true` — the server always forces it.
- The edge returns SSE with **no Content-Type header**; the server re-emits
  `text/event-stream` because the API forwarder picks its parser from it
  (otherwise it tries to JSON-parse the stream and fails with
  `invalid_responses_response`).
- The shared ChatGPT session authorization has a validity window; re-run
  `<router>/bin/model-router codex chatgpt-session enable` if native routing stops.
- Code comments are in French for now (author's working language) — PRs welcome.

## Security

- **No secrets in this repository.** The server reads `TYPESAFE_API_KEY` from an
  env file or the process environment; everything else stays on your machine.
- The server binds `127.0.0.1` only, talks to your local Codex Router only, and
  never logs prompt content beyond a short task excerpt used for calibration.
- Local decision logs and replay data are git-ignored by default.

## Status

Early, but running in production on the author's setup. The joint routing policy needs outcome calibration on real usage; the local
decision and attempt logs provide observations, not quality labels.

## License

MIT
