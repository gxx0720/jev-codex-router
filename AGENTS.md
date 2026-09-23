# AGENTS.md — autonomous install & operations playbook

This file lets a coding agent (Codex, Claude Code, Cursor, …) install, verify
and operate the **Jev Codex Router** on a user's machine without asking for
context it can discover itself. Follow it top to bottom. Do not skip the
verification step after each stage — they are what makes autonomy safe here.

## What you are installing

A local server plus a Codex Router extension that adds one model to the Codex
picker — **"Jev Codex Router"** (`jev/auto`). Normally every turn is classified by
[Jev](https://docs.typesafe.ai) (TypeSafe System One) and served by the
selected model at a thinking depth adapted to the task. The weekly quota guard
forces DeepSeek when 1% or less remains, or the weekly usage cannot be read.
All traffic stays on loopback; the design is fail-open; there is a kill switch.

## Hard rules (never violate)

1. **Never print, log, commit, or transmit secrets** — the TypeSafe API key,
   the router `caller-secret`, or ChatGPT tokens. Reference them by file path.
2. **Edit the source, never the artifact.** `<router checkout>/src/` is the
   router's own source and is meant to be edited: a behaviour bug is fixed
   there, committed on the checkout's branch, with the tests that cover it.
   What is off limits is the *generated and managed* output — `litellm.yaml`
   under the router's state directory is rendered from `src/litellm-config.mjs`
   whenever the catalog changes, and the `codex-router-managed` blocks of
   `~/.codex/config.toml` are written by the CLI, so a hand edit there is
   overwritten rather than applied. Change the generator, or drive the CLI and
   the documented state files (`user-models.json`, `generic-providers.json`),
   and leave the artifacts to be regenerated.
3. The server binds `127.0.0.1` only. Never expose it on another interface.
4. Service installation is user-scoped: `server/install-service.sh` on macOS,
   `server/install-service-linux.sh` on Linux. If the service manager is
   restricted in your environment, skip it and let the user run the matching
   installer in their own terminal. Never fight the restriction.
5. Treat prompt excerpts in local logs (`jev-router-live.jsonl`,
   `shadow-log.jsonl`) as private user data: read locally, never republish.

## Prerequisites (check, and report what you found)

- **macOS or Linux with Codex App or Codex CLI already installed.** This is a
  hard prerequisite; this project does not install Codex. Check `command -v
  codex` (CLI users) and do not modify Codex login/configuration until the user
  approves the relevant step.
- **Git, Node.js ≥ 22.19, and either `uv` or Python ≥ 3.10 with `venv`** for
  Codex Router. Check with `git --version`, `node --version`, `uv --version`,
  and `python3 -V`. Do not silently install package managers/runtimes. If one is
  missing, stop and tell the user exactly which official prerequisite is needed.
- **Python ≥ 3.11** for Jev — `python3 -V`.
- A **TypeSafe API key** for Jev. The server looks for `TYPESAFE_API_KEY` in
  `~/.hermes/.env` first, then `~/.jev.env`, then the process environment.
  If none exists, **stop and ask the user where their key file is — never ask
  for the key value itself in chat.**

## Install Codex Router (if not already installed)

The former `0xNatoshi/jev-codex-router` repository is archived. Use the
maintained Codex Router project referenced by the current official community
installation guide: <https://github.com/duolahypercho/codex-router>. For this
CLI integration, install the CLI-only build without selecting unrelated
providers or collecting their credentials.

1. Check for an existing compatible checkout at
   `~/.local/share/codex-router` and for a working `codex-router` command. If a
   router is present but its version/owner is unclear, **stop and ask**; do not
   replace, stop, or migrate an unknown router.
2. If absent, clone the maintained repository into
   `~/.local/share/codex-router` (do not overwrite an existing directory),
   inspect its `AGENTS.md` and `install.sh`, then run:

   ```bash
   ./install.sh --target codex --no-provider --no-discovery
   ```

   Follow any installer prompts in the user's terminal. This project does not
   need the router's desktop UI.
3. Set `ROUTER="$HOME/.local/share/codex-router/bin/model-router"` and verify
   `"$ROUTER" codex doctor`. Do not proceed until the router reports a healthy
   install, or explain the specific failure and stop.

The official router installation guide is the authority if its command line
changes: <https://codex-router.com/install/>. Codex itself is a user-provided
prerequisite, not installed by either project.

## Install, step by step

### 1 — Start the server

```bash
cd <repo>
python3 server/jev_server.py &            # long-lived; launchd service in step 6
curl -s http://127.0.0.1:4319/health      # expect: {"ok": true, "service": "jev-router"}
curl -s http://127.0.0.1:4319/v1/models   # expect: one model, id "auto"
```

### 2 — Register the local endpoint and model (router CLI)

```bash
cd "$HOME/.local/share/codex-router"
./bin/model-router codex providers generic add jev --name "Jev Router" \
  --base-url http://127.0.0.1:4319/v1 --adapter openai-responses
./bin/model-router codex providers enable jev
./bin/curate-models jev                 # select only the advertised "auto" model
./bin/model-router codex providers
# expect:  SHOW jev   Jev Router (openai-responses)
```

The curation flow owns the model catalog. Do not hand-edit a guessed
`user-models.json` schema; select only the advertised `auto` model and preserve
the text/image modalities that the Jev endpoint reports.

### 3 — Share native ChatGPT access with local clients

This explicitly authorizes other local clients on this OS account to use the
signed-in ChatGPT session. Ask the user to complete/confirm this authorization
before enabling it. If they are not signed in, let them complete the official
interactive Codex login in their own terminal first:

```bash
codex login
./bin/model-router codex chatgpt-session enable
# expect: "enabled for this user's local Codex Router clients (session valid
# for about NNNh)". Re-run this when native calls later return Unauthorized.
```

### 4 — Publish and verify

```bash
./bin/refresh-catalog                     # merged catalog must now contain "jev/auto"
./bin/model-router codex providers        # confirm Jev is SHOW and ready
./bin/model-router codex doctor
codex debug models                        # confirm "jev/auto" is listed
```

### 5 — Persistent service (optional)

Ask the user to run, in **their own Terminal**:

```bash
bash <repo>/server/install-service.sh          # macOS launchd user service
bash <repo>/server/install-service-linux.sh   # Linux systemd --user service
```

Alternative (any scheduler, every 5 min): `<repo>/server/watchdog.sh` —
silent when healthy, restarts the server when down.

### 6 — Restart Codex

Fully quit and reopen the Codex app so it reloads the picker catalog, then the
user can select **Jev Codex Router**.

## End-to-end verification (must pass before declaring success)

```bash
SEC=$(cat ~/.codex/codex-router/caller-secret | tr -d '\n')
curl -s -N -m 120 -X POST "http://127.0.0.1:4202/_codex-router/$SEC/v1/responses" \
  -H 'Content-Type: application/json' \
  -d '{"model":"jev/auto","input":[{"role":"user","content":[{"type":"input_text","text":"Say OK"}]}],"stream":true}' | head -c 400
```

Expect an SSE stream: `data: {"type":"response.created",...,"model":"gpt-5.6-luna",…`
(a trivial prompt routes to luna) ending with `response.completed` and
`data: [DONE]`. Then:

```bash
tail -1 ~/.codex/codex-router/jev-router-live.jsonl
# expect one JSON line: gate=apply, tier, conf, depth, model, effort, speed,
# jev_ms, total_ms, status=200, out=sse
```

## Operations

- **Decision log**: `~/.codex/codex-router/jev-router-live.jsonl` — one line per
  routed turn.
- **Ask surface**: `POST /ask` (also `/v1/ask`) — typed pass-through to System
  One for local callers with their own question set (state ≤ 120k chars, ≤ 40
  questions, caller state never logged). `502 jev: HTTP Error 402` means the
  TypeSafe account is out of credits; `503` means no key was found.
- **Kill switch** (instant, no restart): `touch ~/.codex/codex-router/jev-router.off`
  → the server relays to astra without calling Jev. Remove the file to re-enable.
- **Codex-dry tandem** (only while native usage is exhausted):
  `touch ~/.codex/codex-router/jev-router.codex-dry` → frontier-tier calls go to
  `opencode-go/glm-5.3-flash`, every other tier to
  `opencode-go/deepseek-v4.1-flash`; remove the file to return to the
  luna/sol/astra triptych. An automatic flip (429 / usage-limit response) also
  retries the failed call on the tandem, then lasts until the instant the edge
  announced for the window reset (30 minutes when the refusal announces none,
  one week at most) — `cat ~/.codex/codex-router/jev-router.codex-dry.json`
  reads the reason and `until_iso` — and is cleared by the next successful
  native call. Log fields to watch: `dry`, `native`, `retried`.
- **Weekly quota guard**: `routing-config.json` defaults to a 1% weekly
  remaining threshold and forces `deepseek/deepseek-v4-flash-vision-exp:low`.
  Jev reads the seven-day window from Codex app-server before every model call;
  an unavailable reading also forces DeepSeek. The route log records
  `weekly_remaining_percent` and `weekly_quota_guard`.
- **Thread display**: streamed reasoning summaries get the routed tag appended
  in place ( · 🧠sol:low · , separators on both sides so the next summary part
  never glues to the tag; one glyph per route — ⚡luna, 🧠sol, 🚀astra,
  🐳deepseek/✨glm in tandem). Each assistant text message also starts with the
  actual model and thinking depth by default, including replies without a
  reasoning summary. `touch ~/.codex/codex-router/jev-router.signature.off`
  hides this header; remove the file to show it again. The former opt-in
  `jev-router.signature` file is no longer needed.
- **Shadow mode**: `touch ~/.codex/codex-router/jev-router.shadow` → decisions
  are logged (`would` field) while every call is still served by astra.
- **Debug capture** (bounded): `touch ~/.codex/codex-router/jev-router.debug`
  → request shapes in `jev-router-debug.jsonl` and raw response streams in
  `jev-router-debug-stream.log`. Remove the file to stop.
- **Tune the policy**: the shared contract in `server/routing_policy.py`. Keep decisions
  joint and evidence-based; restart the server after edits.
- **Backtest**: `python3 poc/backtest_savings.py --days 7` (see BACKTEST.md).
- **Disable**: `./bin/model-router codex providers disable jev` (keeps state);
  full rollback: also `./bin/model-router codex chatgpt-session disable` and stop the
  service (`launchctl bootout gui/$(id -u)/com.thibaultsaintjean.jev-router`).

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `{"detail":"Unauthorized"}` from the caller edge | native sharing off | `./bin/model-router codex chatgpt-session enable` |
| `{"detail":"Stream must be set to true"}` | the caller edge streams only | send `"stream": true`; the bundled server forces it |
| HTTP 502 `provider_api_proxy_error` on jev-auto | server-side error | check the `status`/`out` fields in `jev-router-live.jsonl`, and the server's stderr log |
| "Jev Codex Router" absent from the picker | not published/visible, or Codex not restarted | `./bin/refresh-catalog`, `./bin/model-router codex providers`, full Codex restart |
| Native 429 / "usage limit" while routing | ChatGPT usage window exhausted | expected: the Codex-dry tandem takes over (`jev-router.codex-dry.json`); delete the manual file to re-probe sooner |
| Jev calls fail with `402 Payment Required` (`gate=codex_dry(fallback)`, `tier` null in the log) | the TypeSafe account is out of credits | expected: the router keeps serving through the tandem; add credits at console.typesafe.ai to restore classification |
| `Unknown API gateway model: jev-auto` | catalog not republished | `./bin/refresh-catalog` |
| Jev returns HTTP 422 | request body missing `"model"` | always send `"model": "jev-latest"` to the System One API |
| Native calls fail after a few days | shared session expired | re-run `./bin/model-router codex chatgpt-session enable` |
| Service manager rejected inside a supervised agent | environment restriction | use the watchdog; let the user run the OS-specific installer |

## Latency & cost notes

- The current policy is `joint-v1-standard`: Jev chooses one model/effort pair
  per model call by default, including tool steps and post-compaction calls.
  Set `sticky_turn_enabled=true` only when one route per user turn is desired.
  All tiers use adaptive effort and standard speed; never force
  Luna to max or enable Fast mode.
- No scenario overrides, target model shares, or confidence threshold may
  replace a valid Jev choice with Sol, Luna or Astra. Confidence is diagnostic.
- Provider/schema failures remain distinct: Astra at medium, logged as a
  technical fallback. Kill switch and exhausted-native-quota handling still apply.
- Jev usage and upstream per-attempt tokens are logged when available. Run
  `python3 server/report_routing.py --days 7` for native-only credit estimates;
  unknown usage remains unknown and reasoning tokens are not counted twice.
- `BACKTEST.md` documents the old policy's fixed-token simulation. It is not a
  measurement of current quota savings or result quality.
