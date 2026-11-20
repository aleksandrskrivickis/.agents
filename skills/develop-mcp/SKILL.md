---
name: develop-mcp
description: 'Use when configuring or building MCP servers for a coding agent — `.mcp.json` and `claude_desktop_config.json`, `${VAR}` / `${VAR:-default}` environment expansion and which fields it covers, getting a credential into a server without putting it in a config file or in the model''s context, wrapper scripts over an OS keychain (`security find-generic-password`, `secret-tool`, Credential Manager), secrets-manager run-wrappers (`op run`, `infisical run`, `doppler run`), OAuth 2.1 for remote servers versus static bearer tokens for local stdio ones, `--scope project` so a team shares references rather than values, Desktop Extension (`.mcpb`) keychain storage, least-privilege tokens per server, and debugging a 401 that only happens in the desktop app. Covers the config and secret-handling surface, not the MCP protocol itself.'
---

# MCP servers: configuration and secret handling

> **What this is.** The plumbing layer around Model Context Protocol servers: how a server is
> declared, how a credential reaches it, and which of those paths leak. The governing rule is
> architectural rather than hygienic — **the server process holds the credential and the agent only
> ever sees tool results** — and most of what follows is the consequence of taking that seriously.
>
> It does **not** cover the MCP protocol itself (message shapes, transports, capability
> negotiation), nor writing the tools a server exposes. Distilled from configuring a personal
> server ecosystem across Claude Code, the Claude desktop app and VS Code; every value here is a
> placeholder.

## Detailed references

- [secret-injection.md](./references/secret-injection.md) — the four injection layers ranked, the
  wrapper-script pattern in full, what `--scope project` commits, and the failure modes of each.

## The rule that everything else follows from

**A secret that enters the model's context is compromised.** Not "potentially" — treat it as spent.
Context is logged, summarised, replayed into later turns, and reachable by prompt injection from any
untrusted content the agent reads. So the design is fixed:

```
Agent  ──calls──▶  create_ticket(title, body)      ← no credential in the call
                        │
                   MCP server process              ← holds the token, injects it
                        │
                   Upstream API
```

The agent never handles the token, never sees it in a tool result, and never needs to. Any design
where the agent passes a credential as a tool argument, or reads one from a file to use later, has
already lost — fix the server, not the prompt.

Two corollaries worth stating because they are easy to violate accidentally:

- **A tool must not return the credential in its output**, including inside an error. An upstream
  401 that echoes the Authorization header into the agent's context is the same leak by a slower
  route.
- **A server is a supply-chain dependency.** It runs on your machine with your token. Pin versions,
  and read what a third-party server does before handing it anything.

## Environment expansion is the mechanism, not the storage

Claude Code's `.mcp.json` expands environment variables, which is what lets the config file be
committed with no secrets in it:

```json
{
  "mcpServers": {
    "tickets": {
      "command": "npx",
      "args": ["-y", "@example/tickets-mcp"],
      "env": { "TICKETS_TOKEN": "${TICKETS_TOKEN}" }
    },
    "internal-api": {
      "url": "${INTERNAL_API_URL:-https://api.internal.example/mcp}",
      "headers": { "Authorization": "Bearer ${INTERNAL_API_TOKEN}" }
    }
  }
}
```

- `${VAR}` expands to the variable's value; `${VAR:-default}` falls back.
- Expansion works inside **`command`, `args`, `env`, `url` and `headers`**.
- **A required variable with no value and no default makes the config fail to parse.** That is the
  good outcome: a loud error instead of a server that starts with a broken auth header and fails
  opaquely on first use. Do not add a `:-` default to silence it unless the default is genuinely
  valid.

Expansion deliberately reads from the environment and substitutes — it has no opinion about where
the value came from. That is what makes it compose with any secret store, and it is also why
expansion alone is not a secret-management strategy. **How the variable gets set is the actual
decision**, and it is the subject of
[references/secret-injection.md](./references/secret-injection.md).

## The rules that prevent most of the failures here

1. **Never put a secret in the model's context.** The server injects the credential; the agent sees
   results. Everything else on this list is downstream of this.
2. **Config files hold references, never values.** `${VAR}` in `.mcp.json`, `op://vault/item/field`
   in a `.env` template. Then the file is reviewable, diffable and committable.
3. **Prefer an official OAuth connector to a local server with a static key.** Check for one
   *first*. The MCP spec supports OAuth 2.1 for remote servers, so hosted connectors (Slack,
   Atlassian, Google, Notion) hand you short-lived, scoped, revocable tokens and nothing to store.
   Static keys are often unavoidable for local stdio servers, which is exactly why they need the
   care in the reference.
4. **One narrowly-scoped credential per server.** Read-only where the work is read-only; one
   workspace, not the whole tenant. If a server is compromised or a prompt injection drives it, the
   blast radius is that token's scope and nothing more.
5. **Expansion is per-host, not universal.** `.mcp.json` in Claude Code expands variables;
   `claude_desktop_config.json` does not. Confirm which file and which host you are editing before
   assuming a reference will resolve.
6. **A GUI app does not inherit your shell profile.** Any scheme that exports a variable in
   `.zshrc` works in a terminal and silently fails when the app is launched from the dock. Launch
   from the terminal, or move the injection into the server's own `command`.
7. **Treat a 401 as a resolution question first.** Before investigating the upstream API, check
   whether the server received the literal `${TOKEN}` string. That one check separates a
   configuration bug from a credentials bug and saves most of the debugging time.

## Quick symptom → fix index

| Symptom | Likely cause / fix | Reference |
|---|---|---|
| 401 from the server, token is definitely correct | The server received the literal `${TOKEN}` — expansion did not run on this host | secret-injection |
| `${VAR}` works in the CLI but not in the desktop app on macOS | A known expansion gap between the two; launch from a terminal or wrap the `command` | secret-injection |
| Works in a terminal, fails when launched from the dock | GUI apps do not inherit the shell profile that exported the variable | secret-injection |
| `claude_desktop_config.json` keeps the literal reference | That file does not expand variables at all — make `command` a wrapper script | secret-injection |
| Config refuses to parse after adding a server | A referenced variable has no value and no default — this is the intended fail-fast | — |
| A teammate's server works and yours doesn't | The shared `.mcp.json` is identical by design; the difference is the environment each machine supplies | secret-injection |
| Secret ended up in a transcript | A tool returned it, or an error echoed the auth header — fix the server's output and rotate | — |
| Row of plaintext keys in a dotfile | Move to a keychain read or a run-wrapper; the dotfile is the weakest tier | secret-injection |

## Commands

```bash
# Add a server so the config is committable (references only, no values)
claude mcp add --scope project tickets -- npx -y @example/tickets-mcp

# Launch the agent through a secrets-manager wrapper: values exist only in this process tree
op run --env-file=.env.tpl -- claude
infisical run -- claude
doppler run -- claude

# Read one secret from the OS keychain (macOS / Linux)
security find-generic-password -s tickets-token -w
secret-tool lookup service tickets-token
```

## Upstream documentation (sources)

- Model Context Protocol — specification: <https://modelcontextprotocol.io/>
- Claude Code — MCP configuration: <https://docs.claude.com/en/docs/claude-code/mcp>
- Claude Code — settings and `.mcp.json`: <https://docs.claude.com/en/docs/claude-code/settings>

## When to use this skill

- Adding an MCP server to a project or to a personal setup, and deciding where its credential
  lives.
- Debugging a server that authenticates in one host or launch context and not another.
- Setting up a shared `.mcp.json` for a team, where the config must be identical and the secrets
  must not be.
- Reviewing a server you did not write before giving it a token.

## Related skills

- [develop-databricks](../develop-databricks/SKILL.md) — the same split applied to a different
  runtime: non-secret configuration in one place, the credential resolved at run time from a scope.
- [develop-infrastructure](../develop-infrastructure/SKILL.md) — Key Vault and managed identity,
  for the case where the consumer is a cloud workload rather than a local agent.
