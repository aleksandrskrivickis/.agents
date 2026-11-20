# Getting a credential into an MCP server

> **Source.** `[repo]` — from configuring a personal server ecosystem across Claude Code, the Claude
> desktop app and VS Code. `[docs]` marks documented behaviour; `[deduced]` an inference; `[?]` a
> claim worth re-checking, because this surface moves.

[The skill overview](../SKILL.md) establishes *that* the server holds the credential and the agent
never sees it. This file is *how* the value reaches the server process, and what breaks in each
approach.

## The four layers, weakest to strongest

| Layer | Secret at rest | Good for |
|---|---|---|
| **1. Gitignored `.env`, sourced from a profile** | Plaintext on disk | Low-stakes keys; still far better than hardcoding in the config |
| **2. OS keychain, read in the shell profile** | Encrypted by the OS | A personal machine, terminal-launched agents |
| **3. Secrets-manager run-wrapper** | Never on disk | The default for anything shared or production-adjacent |
| **4. OAuth 2.1 on a remote server** | No stored credential at all | Anything with an official connector |

They are not alternatives so much as a ladder: each removes one place the secret can be read. Climb
until the remaining exposure is acceptable rather than picking by preference.

### Layer 2 — keychain reads

```bash
# macOS, in ~/.zshrc
export TICKETS_TOKEN="$(security find-generic-password -s tickets-token -w)"

# Linux (libsecret)
export TICKETS_TOKEN="$(secret-tool lookup service tickets-token)"
```

Nothing plaintext in a dotfile, and `.mcp.json` still only carries `${TICKETS_TOKEN}`. The catch is
the launch context — see *The GUI problem* below.

On Windows the equivalent is Credential Manager, read through `cmdkey`/PowerShell's
`Get-StoredCredential`, which is clumsier to inline into a profile; the wrapper-script pattern is
usually the better fit there. `[deduced]`

### Layer 3 — run-wrappers

The value exists only inside one process tree and never touches disk:

```bash
op run --env-file=.env.tpl -- claude      # 1Password
infisical run -- claude                   # Infisical (open source)
doppler run -- claude                     # Doppler (good per-environment story for teams)
```

`.env.tpl` holds references, not values, and *is* committable:

```
TICKETS_TOKEN=op://Engineering/tickets-mcp/credential
INTERNAL_API_TOKEN=op://Engineering/internal-api/token
```

HashiCorp Vault fits the same shape and is the right answer if you are already in that ecosystem or
need dynamic, short-lived credentials — heavier than the above for a personal setup.

This is the recommended default because it composes: the agent, every MCP server it spawns, and any
script you run in that shell all see the variables, and nothing is left behind when it exits.

### Layer 4 — OAuth, when it exists

The MCP spec supports **OAuth 2.1** for remote servers, which is why hosted connectors need no key
management at all: you authenticate in a browser and the host manages short-lived tokens. `[docs]`

**Check for an official connector before building anything.** If one exists, every section above
becomes unnecessary for that integration. When you build your own *remote* server, implementing
OAuth means tokens are short-lived, scoped and revocable — strictly better than a long-lived key in
an env var. Static keys remain unavoidable for local **stdio** servers, which is the whole reason
layers 2–3 matter.

## The wrapper-script pattern

Required where the host does no expansion (`claude_desktop_config.json`), and the most robust option
everywhere else because it is independent of how the agent was launched. The server's `command`
becomes a script that fetches the secret and `exec`s the real server:

```bash
#!/usr/bin/env bash
# ~/bin/tickets-mcp — fetch the credential, then hand off
set -euo pipefail
export TICKETS_TOKEN="$(security find-generic-password -s tickets-token -w)"
exec npx -y @example/tickets-mcp "$@"
```

```json
{
  "mcpServers": {
    "tickets": { "command": "/Users/me/bin/tickets-mcp" }
  }
}
```

Three details that matter:

- **`exec`, not a plain call.** The server should replace the wrapper in the process table so
  signals and stdio pass straight through; a wrapper left in the middle can break shutdown.
- **`set -euo pipefail`** so a failed keychain read aborts instead of launching the server with an
  empty token — which presents as a confusing upstream 401 rather than a local failure.
- **One script per server**, each reading its own narrowly-scoped credential. A shared wrapper that
  exports every token hands each server all of them and defeats least privilege.

## The GUI problem

Two distinct failures that look identical, and both produce a 401:

1. **Expansion did not run.** There is a reported gap where `${VAR}` in `.mcp.json` resolves in the
   Claude Code CLI but **not** in the desktop app on macOS — the server receives the literal string
   `${TOKEN}`. `[?]`
2. **The variable was never set.** A GUI app launched from the dock or Spotlight does **not**
   inherit `~/.zshrc`, so any `export` there is invisible to it. `[docs]`

The diagnostic that separates them from a genuine credential problem takes one minute: make the
server log the *length* of the token it received, never the value. Zero means case 2; the length of
`"${TOKEN}"` means case 1; the real length means your credential is wrong and the config is fine.

Either way, the fixes are the same two: **launch the agent from a terminal** (so profile exports and
run-wrappers both apply), or **move the injection into the `command`** via a wrapper script, which
is immune to launch context.

## Teams: share the config, not the values

```bash
claude mcp add --scope project tickets -- npx -y @example/tickets-mcp
```

`--scope project` writes the server into `.mcp.json`, which is meant to be committed. Because it
holds only references, the file is **byte-identical for everyone** — the entire difference between
machines is the environment each one supplies, and each teammate keeps their own credential in their
own vault. That property is what makes a config review meaningful: a diff on `.mcp.json` shows a
server being added, never a secret rotating.

Two consequences worth planning for:

- **The README has to say which variables are required**, because the config's fail-fast parse error
  names the variable but not where to get it. A committed `.env.tpl` of references doubles as that
  documentation.
- **Onboarding is a vault grant, not a config change.** That is the point, but it means a new
  teammate's first failure is a parse error, and they need to know it is expected.

## Packaging: Desktop Extensions

A server installed as a **Desktop Extension** (`.mcpb` bundle) has its config fields declared, and
fields marked sensitive are stored in the **OS keychain by the host** rather than in any JSON file.
`[docs]` If you are building servers for your own ecosystem, packaging them this way gets keychain
storage and a cleaner install flow without writing a wrapper script per server — worth preferring
over hand-edited config once you have more than a couple.

## Hygiene for whatever remains

- **Rotate on exposure, not on suspicion of exposure.** If a secret reached a transcript, a log or
  a shared screen, it is spent; rotate it rather than reasoning about who saw it.
- **Scope before storing.** A read-only token in a plaintext `.env` is often a better risk position
  than an admin token in a vault — reducing what the credential can do beats improving where it
  sits.
- **Audit what each server can reach** when you add it, not later. The list of servers is the list
  of things a prompt injection can drive.
- **Pin server versions.** An MCP server auto-updating via `npx -y` is a dependency you re-accept
  on every launch, holding a live credential.

## Sources

- Model Context Protocol — authorization / OAuth: <https://modelcontextprotocol.io/specification/basic/authorization>
- Claude Code — MCP configuration and scopes: <https://docs.claude.com/en/docs/claude-code/mcp>

## Related

- [the skill overview](../SKILL.md) — why the credential must stay out of the model's context, and
  the expansion mechanism itself.
- [develop-databricks](../../develop-databricks/references/administration-credential-management.md) —
  the same pattern in a platform runtime: scope and key *names* as configuration, value resolved at
  run time.
