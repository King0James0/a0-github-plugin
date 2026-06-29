# GitHub plugin for Agent Zero

Gives Agent Zero reliable, skill-guided GitHub abilities through the [`gh`](https://cli.github.com/) CLI. The plugin installs `gh` for you, authenticates it from a token you keep in Agent Zero's Secrets, and bundles a small pack of process skills with tested command templates — so the agent knows the *workflow*, not just the tool, and even smaller local models run GitHub tasks correctly.

## Support

If this plugin is useful to you, you can support the developer.

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-ffdd00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/king0james0) [![Solana](https://img.shields.io/badge/Solana-9945FF?style=for-the-badge&logo=solana&logoColor=white)](https://solscan.io/account/HXrzPqgcxBR9LctTVdTF6xCLpah4hQwyYEevsQ98QvTo) [![Ethereum](https://img.shields.io/badge/Ethereum-3C3C3D?style=for-the-badge&logo=ethereum&logoColor=white)](https://etherscan.io/address/0xfF61681F907fA8DB39C1d23cbdbE89D24A94De17) [![Bitcoin](https://img.shields.io/badge/Bitcoin-F7931A?style=for-the-badge&logo=bitcoin&logoColor=white)](https://mempool.space/address/bc1qyr6x7kmxpy6ke0xutkxg90f30658fnr39h0d7r)

## What it can do

Once installed and given a token, the agent can:

- **Open pull requests** (`github-open-pr`) — create a branch, commit, push, and open a PR with a real title and body.
- **Triage issues** (`github-triage-issue`) — list, read, label, assign, comment on, create, and close issues.
- **Review pull requests** (`github-review-pr`) — read a PR, inspect its diff, check CI status, and approve / comment / request changes.
- **Search GitHub** (`github-search`) — find code, issues, PRs, or repositories, and call the GitHub REST/GraphQL API directly.
- **Watch repos** (`github-watch`) — poll a set of repos for new/updated issues and PRs (and optionally new commits) since the last check, and add/remove/show watched repos. The watched set is the union of the repo list you keep in the plugin's **Config** panel (`watch_repos`) and the repos you Watch on GitHub. Saying "watch owner/name" in chat updates that same config list. Issues + PRs are always checked; enable **Watch commits** to also catch pushes to each repo's default branch. Only the per-repo last-checked timestamps live in a runtime file (`/a0/usr/github-watch/watch_state.json`). For recurring polling, flip on the built-in hourly scheduler (below).
- **Create releases** (`github-create-release`) — tag a version and publish a GitHub release with real, user-facing notes (matched to the project version); refuses to overwrite an existing release.

Each ability ships as a focused skill containing the exact `gh` commands for that workflow, so the agent doesn't have to guess.

## Setup

### 1. Install the plugin
Use any of Agent Zero's install methods: the Plugin Hub (**Browse**), install from a GitHub repo URL, or upload the plugin ZIP. After it lands, enable it in the **Plugins** list. On first run it downloads `gh` into its own folder — this needs outbound internet once.

### 2. Create a GitHub token
Either token type works. A **classic PAT** is the quickest to set up; a **fine-grained token** is more secure (per-repository, least-privilege) and is the better choice if the agent only needs a few repos.

#### Option A — Classic personal access token (simplest)

1. Go to **https://github.com/settings/tokens/new** (or: your avatar → **Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token (classic)**).
2. **Note**: name it something like `agent-zero-github`.
3. **Expiration**: pick a sensible window (e.g. 90 days). Shorter is safer — when it lapses you just regenerate and update the Secret.
4. **Select scopes** — tick the boxes for what you need:

   | Scope | What it enables | Needed for |
   |---|---|---|
   | `repo` | Full read/write on repositories you can access (code, pull requests, issues, commit statuses) | **Required** — open/review PRs, triage issues, push branches, search private repos |
   | `workflow` | Push changes to `.github/workflows/` files | Opening PRs that add or edit GitHub Actions workflows (the push is rejected without it) |
   | `read:org` | Read org and team membership and org projects | Triaging org issues/projects and searching within an organization |
   | `read:user` | Read your own profile | Optional — helps `gh` resolve `@me` filters (e.g. "issues assigned to me") |

   The minimum is **`repo`**. For most users **`repo` + `workflow` + `read:org`** is the comfortable set.
5. Click **Generate token** and **copy it immediately** — GitHub shows it only once. Classic tokens start with `ghp_`.
6. **Org SSO**: if any of your repos belong to a SAML/SSO-protected organization, click **Configure SSO** next to the new token and **Authorize** it for that org, or org calls will return `403`.

#### Option B — Fine-grained personal access token (least-privilege, recommended)

1. Go to **https://github.com/settings/personal-access-tokens/new** (Settings → Developer settings → Personal access tokens → **Fine-grained tokens → Generate new token**).
2. Set a **token name** and **expiration**.
3. **Resource owner**: your own account, or the organization that owns the repos. (Org-owned tokens may need the org to allow fine-grained tokens and may require admin approval.)
4. **Repository access**: choose **Only select repositories** and pick the ones the agent will work on (or **All repositories**).
5. **Repository permissions** — set these to **Read and write**; leave everything else at **No access**:

   | Permission | Level | Needed for |
   |---|---|---|
   | Contents | Read and write | push/pull, branches (open PR), tags + releases (create release) |
   | Pull requests | Read and write | create and review PRs |
   | Issues | Read and write | triage issues |
   | Workflows | Read and write | PRs that touch `.github/workflows/` |
   | Commit statuses | Read-only | `gh pr checks` (CI status) |
   | Metadata | Read-only | mandatory (auto-selected) — repo lookup and search |

6. Click **Generate token** and **copy it**. Fine-grained tokens start with `github_pat_`.

> Tip: grant the least you need — you can always regenerate with more later. Because auth is read fresh on every operation, widening a token just means updating the `GITHUB_TOKEN` Secret (step 3) and restarting; nothing else changes.

### 3. Add the token to Agent Zero Secrets
This is the only configuration step. In Agent Zero:

1. Open **Settings** (gear icon).
2. Go to **External Services → Secrets**.
3. In the **Secrets** box (the masked one — *not* Variables), add a line:
   ```
   GITHUB_TOKEN=ghp_your_token_here
   ```
4. Save.

> The key name `GITHUB_TOKEN` is the default. If you prefer a different key, change `secret_key` in the plugin's config and use that name here instead.

### 4. Restart / re-enable
Restart Agent Zero (or toggle the plugin off and on). That's it — try a prompt like *"open a PR for my changes"* or *"list the open issues on this repo"* and the agent will discover the matching skill and run `gh`.

## How authentication works

Authentication is **stateless** — your token is never copied into a `gh` login file or a git credential store. It lives only in Agent Zero's Secrets, and is read fresh for each operation:

- The plugin installs a thin `gh` wrapper on your `PATH`. Each time `gh` runs, the wrapper reads `GITHUB_TOKEN` from your Secrets and hands it to that single `gh` process (via `GH_TOKEN`, which `gh` reads natively) — then it's gone.
- `git push` / `git pull` for `github.com` are routed through the same wrapper using a scoped git credential helper, so git transport uses the same token without storing it either.

Because the token is read at call time, **rotating it just means updating the Secret** — no re-login. And because Agent Zero masks Secrets from prompts, chat history, and logs, the token never appears in the conversation.

## Configuration

`default_config.yaml` (override per scope in the plugin config UI):

| Key | Default | Meaning |
|---|---|---|
| `transport` | `gh` | How the agent talks to GitHub. `mcp` is planned. |
| `secret_key` | `GITHUB_TOKEN` | Advanced: which A0 Secret holds the token. Only change it if your Secret isn't named `GITHUB_TOKEN` (see Setup). Not shown in the Config panel — edit the config file. |
| `gh_version` | `latest` | Advanced: `gh` release to install, or a pinned tag like `v2.63.2`. Not shown in the Config panel. |
| `watch_repos` | `""` | Authoritative list of `owner/name` repos to watch, one per line. Edited in the Config panel; "watch owner/name" in chat updates it too. |
| `watch_include_subscriptions` | `true` | Also include repos you watch at **All Activity** level on GitHub (`user/subscriptions`). Needs the token's **Watching: Read** permission. **Custom** / **Participating** watches are *not* exposed by GitHub's API — see the note below. This is *Watch*, not *Star*. |
| `watch_scope` | `issues,prs` | What `github-watch` always reports: issues + PRs (comments excluded). |
| `watch_commits` | `false` | Also report new commits on each repo's default branch since the last check. Off by default (commits can be high-volume). |
| `watch_schedule_enabled` | `false` | When true, the plugin self-registers an A0 scheduled task (`GitHub Watch`) that runs the watch on a schedule; false removes it. |
| `watch_interval` | `1h` | How often the poll runs. Preset token: `5m`/`10m`/`15m`/`30m` or `1h`/`2h`/`6h`/`12h`/`24h` (dropdown in the panel). |
| `watch_cron` | `""` | Advanced: a full 5-field cron expression (e.g. `*/15 9-17 * * 1-5`). When set, it overrides `watch_interval`. |
| `watch_reset_context` | `true` | Clear the scheduled task's conversation after each run so its context doesn't grow unbounded over time (each run starts fresh). |
| `watch_notify_chat` | `true` | In-app notification (toast + notifications bell) via A0's built-in `notify_user` tool. No token needed. |
| `watch_notify_telegram` | `false` | Also Telegram the findings when there's new activity. How it's sent depends on `telegram_method`. |
| `telegram_method` | `tool` | `tool` = the scheduled task sends via a Telegram tool it already has (e.g. the YATCA plugin); skipped if none is installed. `direct` = this plugin sends it itself via the Telegram Bot API (no other plugin needed). |
| `telegram_bot` | `""` | (`tool` mode) Which bot the send tool should use, by name. Blank = the default bot. |
| `telegram_secret_key` | `TELEGRAM_BOT_TOKEN` | (`direct` mode) Name of the A0 Secret holding the Telegram bot token. Same Secrets store as the GitHub token. |
| `telegram_chat_id` | `""` | (`direct` mode) Destination chat id. Direct mode can't auto-learn it — get yours from `@userinfobot` on Telegram. |
| `watch_notify_other` | `""` | Free-form delivery instruction the agent tries to fulfill with its tools (e.g. a Discord webhook, email). Best-effort. |
| `watch_enrich` | `false` | Add per-item detail to the report (body snippet, labels, author) **and** a model-written release-note digest to the in-app toast. See *Enrichment* below. |
| `enrich_model` | `utility` | Model tier that writes the digest: **utility** (fast/cheap) or **chat** (your main model). |
| `enrich_method` | `extension` | How the digest is generated: **extension** (deterministic, honours `enrich_model`) or **agent** (prompt-written; reroutes the whole task onto the tier). |

> **⚠️ About "Include GitHub-Watched repos" — important.** GitHub's API only exposes repos you watch at the **All Activity** level (`GET /user/subscriptions`). Repos you watch at **Custom** or **Participating and @mentions** level are **not returned by any GitHub API** and therefore *cannot* be auto-discovered — this is a GitHub limitation, not a plugin one. To have those tracked, either switch them to **All Activity** on GitHub, or (recommended) add them to `watch_repos` directly, which works at any watch level.
>
> Reading your watched repos also requires the token's **Watching: Read** permission. For a **fine-grained PAT**, grant it under **Account permissions → Watching → Read-only** (it's a separate section from Repository permissions). Without it, `user/subscriptions` returns empty and the watch silently uses only your `watch_repos` list. Classic tokens have this via the standard scopes.

### Recurring polling

Turn **Recurring poll** on in the plugin's **Config** panel (or set `watch_schedule_enabled: true`). The plugin registers a scheduled task, `GitHub Watch`, that runs the `github-watch` skill on the **Interval** you pick — presets from every 5 minutes to once a day, or a **custom cron** expression for anything else (default: hourly). Changes apply on save — no restart.

The plugin owns the **schedule only**; delivery runs separately in a normal agent context. Toggle it off (or uninstall) and the task is removed automatically — nothing is orphaned. Every run's full result is kept in A0's **Scheduler** UI, where you can also edit or disable the task.

#### Where findings go

Pick one or more under **Notify** in the Config panel:

| Channel | What it does | Setup |
|---|---|---|
| **In-app** | Toast + notifications bell, via the built-in `notify_user` tool | None — recommended default |
| **Telegram** | Messages the report when there's new activity | See below |
| **Other** | A free-form instruction the agent carries out with its tools (e.g. a Discord webhook, email) | Best-effort |

#### Telegram: two methods

Set **Telegram method** in the panel:

- **Tool** — sends through a Telegram tool the agent already has, such as the [YATCA](https://github.com/mirecekd/yatca) plugin. No token configured here; skipped if no such tool is installed.
- **Direct** — this plugin sends the report itself via the Telegram Bot API, with **no dependency on any other plugin**. Deterministic and exact (sent straight from the watch script, emoji intact).

**Direct mode setup**

1. Add your bot token as an A0 Secret: **Settings → External Services → Secrets**, named `TELEGRAM_BOT_TOKEN` (or whatever you set `telegram_secret_key` to).
2. Message `@userinfobot` on Telegram to get your chat ID, and put it in **Chat ID** (`telegram_chat_id`).
3. Set **Telegram method** to **Direct**. The next poll with new activity sends straight to Telegram.

### Enrichment

Turn **Enable enrichment** on (`watch_enrich`) for two things when there's new activity:

- **Richer report** — each item gains a body snippet, labels, and author (commit author for commits). This goes into the full report (chat + Telegram).
- **Release-note digest** — a short, model-written summary of what changed, posted to the **in-app toast only**. Chat and Telegram still get the full report, so the toast stays glanceable while the detail lives in the report.

Two settings control the digest:

- **Digest model** (`enrich_model`) — **Utility** (fast/cheap, recommended for a summary) or **Chat** (your main model).
- **Digest method** (`enrich_method`):
  - **Extension** *(recommended)* — a plugin extension calls the chosen model and posts the digest. Deterministic, and the only mode that honours **Digest model**.
  - **Agent** — the scheduled-task agent writes the digest itself. Lighter, but less reliable, and it reroutes the **whole task** onto the chosen tier (so a weaker tier affects the entire run, not just the digest).

It all uses A0's own model framework — no API keys or extra config, and nothing is sent off-box beyond the model you've already configured.

## Uninstalling

Uninstall through the **Plugins UI** for a clean removal: the `gh` binary and the plugin's files are deleted with the plugin folder, and the uninstall hook removes the `gh` wrapper and the git credential helper it added. (A manual `rm -rf` of the folder skips that hook, leaving a dangling `/usr/local/bin/gh` wrapper to remove by hand.)

## Notes

- The downloaded `gh` binary lives entirely inside the plugin directory, and is **verified against GitHub's published SHA-256 checksum** before it is installed — a tampered or corrupted download is refused.
- The only changes outside the plugin folder are the `gh` wrapper on `PATH` and one `github.com` git credential-helper line — both removed on uninstall.
- The token is read from your A0 Secret at call time and passed only to the `gh`/`git` process that needs it; it is never written to a `gh` login file or git credential store, and never printed.
- Requires outbound network access on first run to download `gh`.

## Citing

If you use this in your work, please cite it (use the **"Cite this repository"** button on GitHub, or):

```bibtex
@misc{a0githubplugin2026,
  title        = {a0-github-plugin: skill-guided GitHub operations for Agent Zero},
  author       = {King0James0},
  year         = {2026},
  howpublished = {\url{https://github.com/King0James0/a0-github-plugin}},
  note         = {GitHub repository}
}
```

## License

MIT — see [LICENSE](LICENSE).
