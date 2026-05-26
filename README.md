# GitHub plugin for Agent Zero

Gives Agent Zero reliable, skill-guided GitHub abilities through the [`gh`](https://cli.github.com/) CLI. The plugin installs `gh` for you, authenticates it from a token you keep in Agent Zero's Secrets, and bundles a small pack of process skills with tested command templates — so the agent knows the *workflow*, not just the tool, and even smaller local models run GitHub tasks correctly.

## What it can do

Once installed and given a token, the agent can:

- **Open pull requests** (`github-open-pr`) — create a branch, commit, push, and open a PR with a real title and body.
- **Triage issues** (`github-triage-issue`) — list, read, label, assign, comment on, create, and close issues.
- **Review pull requests** (`github-review-pr`) — read a PR, inspect its diff, check CI status, and approve / comment / request changes.
- **Search GitHub** (`github-search`) — find code, issues, PRs, or repositories, and call the GitHub REST/GraphQL API directly.

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
   | Contents | Read and write | push/pull, branches (open PR) |
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
| `secret_key` | `GITHUB_TOKEN` | Which A0 Secret holds the token. |
| `gh_version` | `latest` | `gh` release to install, or a pinned tag like `v2.63.2`. |

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
