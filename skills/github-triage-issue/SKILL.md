---
name: github-triage-issue
description: Triage GitHub issues with the gh CLI - list, read, label, assign, comment on, create, or close issues. Use when the user asks to look at issues, file or open an issue, label/assign/close an issue, or reply to one. Assumes the github plugin has authenticated gh.
---

# Triage a GitHub Issue

Pick the step that matches the request. Run from inside the target repo (or pass `--repo owner/name`).

List and read:
```bash
gh issue list --state open --limit 30
gh issue list --label bug --assignee @me
gh issue view <number>
gh issue view <number> --comments
```

Create:
```bash
gh issue create --title "<title>" --body "<details>" --label "<label>"
```

Act on an existing issue:
```bash
gh issue comment <number> --body "<message>"
gh issue edit <number> --add-label "<label>" --add-assignee <user>
gh issue close <number> --comment "<reason>"
gh issue reopen <number>
```

Rules:
- Read the issue (`gh issue view`) before commenting or closing so the response is on-topic.
- Confirm destructive actions (close, bulk-label) with the user unless they already asked for them explicitly.
- Report the issue URL after creating or modifying.

Failure handling:
- "label not found" -> list available labels with `gh label list` and pick an existing one or create it with `gh label create`.
- Auth/permission error (not logged in, or `403 Resource not accessible by personal access token`) -> the `GITHUB_TOKEN` Secret is missing or under-scoped (needs Issues read/write, `read:org` for org issues; classic: `repo`). Tell the user to update that token under Settings > External Services > Secrets. Do NOT run `gh auth login` — this plugin authenticates from the Secret.
