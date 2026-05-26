---
name: github-search
description: Search GitHub with the gh CLI - find code, issues, pull requests, or repositories, and call arbitrary REST/GraphQL endpoints via gh api. Use when the user asks to find or search for something on GitHub, locate a repo, look up where code/text appears, or query the GitHub API. Assumes the github plugin has authenticated gh.
---

# Search GitHub

Pick the command for what is being searched. Quote multi-word queries.

Code (where a string appears):
```bash
gh search code "<query>" --limit 30
gh search code "<query>" --owner <owner> --language <lang>
```

Issues and pull requests:
```bash
gh search issues "<query>" --state open --limit 30
gh search prs "<query>" --author <user> --state merged
```

Repositories:
```bash
gh search repos "<query>" --limit 20
gh search repos "<query>" --owner <owner> --language <lang>
```

Arbitrary API call (when no search subcommand fits):
```bash
gh api /repos/<owner>/<repo>/contributors
gh api graphql -f query='<graphql>'
```

Rules:
- Start narrow (`--owner`, `--language`, `--state`) and widen only if results are empty.
- Report results as a short list of `owner/repo#number - title (url)`; do not dump raw JSON unless asked.
- Prefer `gh api` with `-q` (jq) to extract just the fields the user needs.

Failure handling:
- Empty results -> loosen filters or rephrase the query before concluding nothing exists.
- Rate-limit / 403 -> check `gh api rate_limit`; authenticated calls have a much higher limit. A `403 Resource not accessible by personal access token` instead means the `GITHUB_TOKEN` Secret is under-scoped — tell the user to update it under Settings > External Services > Secrets. Do NOT run `gh auth login` — this plugin authenticates from the Secret.
