---
name: github-review-pr
description: Review a GitHub pull request with the gh CLI - read it, inspect the diff and checks, check out the branch, and submit a review (approve, comment, or request changes). Use when the user asks to review a PR, look at a pull request's changes, check CI status, or approve/request changes. Assumes the github plugin has authenticated gh.
---

# Review a GitHub PR

Run from inside the target repo. `<number>` is the PR number; omit it to act on the current branch's PR.

1. Read the PR and its conversation.
   ```bash
   gh pr view <number>
   gh pr view <number> --comments
   ```

2. Inspect the changes and CI.
   ```bash
   gh pr diff <number>
   gh pr checks <number>
   ```

3. To run or test it locally, check out the PR branch.
   ```bash
   gh pr checkout <number>
   ```

4. Submit the review. Choose exactly one verdict and always include a body.
   ```bash
   gh pr review <number> --approve --body "<summary>"
   gh pr review <number> --comment --body "<observations>"
   gh pr review <number> --request-changes --body "<what must change>"
   ```

Rules:
- Always read the diff (step 2) before submitting a verdict in step 4.
- Use `--request-changes` only for concrete, actionable blockers; otherwise `--comment`.
- Do not approve a PR with failing required checks unless the user explicitly tells you to.

Failure handling:
- "no pull requests found" -> the current branch has no open PR; pass an explicit `<number>`.
- Auth/permission error (not logged in, or `403 Resource not accessible by personal access token`) -> the `GITHUB_TOKEN` Secret is missing or under-scoped (needs Pull requests access; classic: `repo`). Tell the user to update that token under Settings > External Services > Secrets. Do NOT run `gh auth login` — this plugin authenticates from the Secret.
