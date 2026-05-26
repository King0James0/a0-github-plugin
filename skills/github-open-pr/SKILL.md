---
name: github-open-pr
description: Open a GitHub pull request with the gh CLI. Use when the user asks to open or create a PR, submit a branch for review, raise a pull request, or push changes and open a PR. Assumes the github plugin has authenticated gh.
---

# Open a GitHub PR

Run these in order from inside the target git repository. Stop and report at the first failure.

1. Confirm auth. If this fails, tell the user to add a GitHub token as the `GITHUB_TOKEN` Secret under Settings > External Services > Secrets, then stop.
   ```bash
   gh auth status
   ```

2. Identify the default branch and current branch.
   ```bash
   gh repo view --json defaultBranchRef -q .defaultBranchRef.name
   git rev-parse --abbrev-ref HEAD
   ```

3. If on the default branch, create a feature branch first (never open a PR from the default branch).
   ```bash
   git switch -c <short-descriptive-branch>
   ```

4. Stage and commit the work. Use a concise, imperative commit subject.
   ```bash
   git add -A && git commit -m "<subject>"
   ```

5. Push the branch and set upstream.
   ```bash
   git push -u origin HEAD
   ```

6. Create the PR against the default branch. Write a real title and body; do not leave them empty.
   ```bash
   gh pr create --base <default-branch> --head <current-branch> \
     --title "<title>" --body "<summary of what changed and why>"
   ```

7. Report the PR URL printed by step 6 back to the user.

Failure handling:
- "could not determine base repo" -> the directory is not a GitHub remote; confirm `git remote -v` and the repo exists on GitHub.
- "a pull request already exists" -> show it with `gh pr view --web` instead of creating a new one.
- Auth/permission error (not logged in, or `403 Resource not accessible by personal access token`) -> the `GITHUB_TOKEN` Secret is missing or under-scoped (needs Contents + Pull requests write; classic: `repo`). Tell the user to update that token under Settings > External Services > Secrets. Do NOT run `gh auth login` — this plugin authenticates from the Secret.
