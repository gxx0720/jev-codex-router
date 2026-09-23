# Operations runbook

`jev_server.py` listens on `127.0.0.1:4319` and receives Responses requests for
the `jev/auto` model. For each turn it asks Jev for a route
(tier + thinking depth), applies the routing policy, and relays the request to
the Codex Router's local caller edge, which serves native GPT models from the
shared ChatGPT session.

## Lifecycle

Codex App or Codex CLI must already be installed, and Codex Router plus Jev
must run on the same host. Jev relays through that host's Codex Router loopback
edge at `127.0.0.1:4202`; it does not bypass Codex Router or share the Windows
service remotely. For a fresh macOS/Linux setup, follow the repository's
[agent installation playbook](../AGENTS.md), which installs the maintained
Codex Router CLI-only build when needed. Do not overwrite an unknown router.

On macOS/Linux, run `codex` from the CLI and select `Jev Codex Router` after the
router catalog is refreshed. For a direct CLI endpoint override, follow
[Codex's user-level configuration guidance](https://learn.chatgpt.com/docs/config-file/config-advanced)
and preserve the protected caller secret; never put it in shell history or a
project-level config. Set `CODEX_HOME` consistently for Codex, Jev, and the
Codex Router when using a non-default profile.
Stop a manually started `jev_server.py` before installing the macOS launchd
service; the installer checks that port 4319 is free after stopping any prior
managed job and will fail rather than mistake the manual process for its own.

| Action | Command |
|---|---|
| Check installation without inference | `python3 server/verify_install.py` from the Jev repository |
| Test the full route (one real request) | `python3 server/verify_install.py --live` (may consume quota/credits; prints no secrets or reply text) |
| Decision log | `tail -f "${CODEX_HOME:-$HOME/.codex}/codex-router/jev-router-live.jsonl"` |
| Model/thinking header | Shown above every assistant message by default; `touch "${CODEX_HOME:-$HOME/.codex}/codex-router/jev-router.signature.off"` to hide it, remove that file to restore it |
| Kill switch (no Jev → configured off route, currently GPT-6 Sol) | `touch "${CODEX_HOME:-$HOME/.codex}/codex-router/jev-router.off"`; remove file to re-enable |
| Install macOS service | `bash server/install-service.sh` (your Terminal) |
| Install Linux user service | `bash server/install-service-linux.sh` (no root; systemd user session required) |
| macOS status/restart | `launchctl print gui/$(id -u)/com.thibaultsaintjean.jev-router` / `launchctl kickstart -k gui/$(id -u)/com.thibaultsaintjean.jev-router` |
| Linux status/restart | `systemctl --user status jev-codex-router` / `systemctl --user restart jev-codex-router` |
| Watchdog (either OS) | `bash server/watchdog.sh`, e.g. cron every 5 min |
| Disable the provider | `./bin/model-router codex providers disable jev` |
| Revoke native sharing | `./bin/model-router codex chatgpt-session disable` |

## After a Codex Router update

Provider and model state live outside the router checkout, so updates should not
touch them. Verify anyway:

1. `<router>/bin/model-router codex providers` → should show `SHOW` and `ready` for Jev.
2. `cat ~/.codex/codex-router/model-picker.json` → `jev/auto` under `visible`.
3. `curl -s http://127.0.0.1:4319/health` → `{"ok": true...}`.
4. If needed: `<router>/bin/refresh-catalog`, then restart Codex.

## Troubleshooting

- **`invalid_responses_response` in router logs / “unavailable right now” in
  Codex**: the API forwarder parsed our reply as JSON instead of SSE. The server
  forces `Content-Type: text/event-stream` on streamed replies for exactly this
  reason; make sure you run the current `jev_server.py`.
- **401 / route refused by the edge**: the shared ChatGPT session expired —
  re-run `<router>/bin/model-router codex chatgpt-session enable`.
- **Every turn takes the configured fallback**: check the decision log (`gate` field) — the
  kill switch may be on, or the TypeSafe key is unreadable (look for
  `jev_error` / `no_key_or_task` gates).
- **Model missing from the picker**: re-run `<router>/bin/refresh-catalog`,
  verify the provider is enabled and model is curated, then fully restart Codex.

### Model visible but rejected by ChatGPT

`The 'jev/auto' model is not supported when using Codex with a ChatGPT account`
can mean the model is selected while the OpenAI provider still points directly
at OpenAI. Listing a model in a catalog, or declaring `[model_providers.jev]`,
does not associate an existing task with that provider.

1. Inspect `./bin/model-router codex status`: check `model_provider` and the redacted
   `openai_base_url`, not just whether the service is running.
2. Verify the main router has the enabled `jev` generic provider and the
   `jev/auto` entry in its curated model catalog. A direct Codex provider declaration
   is a separate configuration. Reload the router after restoring its routes;
   its startup regenerates the gateway configuration from source.
3. Preserve a user-owned `model_catalog_json`. With the built-in `openai`
   provider, Codex supports a user-level `openai_base_url` pointing to the
   router's authenticated loopback Responses entry. Use Codex's
   `config/value/write` API for this setting; resolve the caller capability
   locally from its protected file, never print it or put it in command
   arguments. Leave other provider definitions and model defaults intact.
4. Verify a small request through **4202 → Jev 4319 → native 4202**, then through
   an ephemeral Codex invocation reading the saved configuration. Checking
   Jev's health alone does not exercise the client transport.
5. Quit and reopen Codex CLI (or desktop) on the host to reload the configuration before
   retrying the existing task from desktop or mobile.

The built-in OpenAI transport override was verified with Codex
`0.155.0-alpha.9.2`; no switch to a different provider or catalog was needed.
See the [official configuration documentation](https://learn.chatgpt.com/docs/config-file/config-advanced)
for the distinction between the built-in endpoint override and custom providers.

## Design notes

- The edge emits SSE with no Content-Type; we always re-emit
  `text/event-stream; charset=utf-8` on stream relays.
- `stream: true` is forced upstream (the edge requires it); non-stream callers
  get the final response object assembled from the SSE stream.
- One Jev decision per request (≈0.6 s, included in total latency). Tool-loop
  continuations are re-classified on the same last-user text; they land on the
  same tier in practice, and everything is logged for tuning.
