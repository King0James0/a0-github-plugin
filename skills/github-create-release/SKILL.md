---
name: github-create-release
description: Cut a GitHub release with real release notes using the gh CLI. Use when the user asks to create or publish a release, cut a release, tag a version, ship a version, draft release notes, or "release vX.Y.Z". Assumes the github plugin has authenticated gh.
---

# Create a GitHub release

Publish a tagged GitHub release **with user-facing notes**. Run these in order from inside the target git repository. Stop and report at the first failure. A release is more than a tag — `git push` alone leaves the Releases tab empty, so always cut a release and always write real notes (never publish empty or auto-only notes).

1. Confirm auth. If this fails, tell the user to add a GitHub token as the `GITHUB_TOKEN` Secret under Settings > External Services > Secrets, then stop.
   ```bash
   gh auth status
   ```

2. Decide the version tag (format `vX.Y.Z`). Use the version the user gave. If they didn't give one, infer the project version, then confirm it with the user before tagging:
   ```bash
   grep -E '^version:' plugin.yaml 2>/dev/null \
     || sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' package.json 2>/dev/null \
     || git describe --tags --abbrev=0 2>/dev/null
   ```
   For a plugin, the tag MUST match `plugin.yaml` `version:`; if they differ, bump `plugin.yaml` first and commit it so the release matches what actually installs.

3. Refuse to clobber an existing release. If this prints `EXISTS`, stop and ask the user for a new version — never overwrite a published release:
   ```bash
   gh release view <vX.Y.Z> >/dev/null 2>&1 && echo "EXISTS — stop"
   ```

4. Make sure everything being released is committed and pushed (a release points at a commit that must exist on the remote):
   ```bash
   git status --porcelain   # expect empty; commit first if not
   git push                 # push the branch you are releasing
   ```

5. Find the previous release and review what changed since it (omit the range for a first release):
   ```bash
   git describe --tags --abbrev=0 2>/dev/null      # previous tag, if any
   git log <previous-tag>..HEAD --oneline
   ```

6. Write real, user-facing notes — what's new / changed / unchanged, in the user's voice (not raw commit subjects). Keep them clean: no secrets, tokens, internal hostnames/IPs, or local file paths, and no AI / "Generated with" attribution. Put them in a file to avoid shell-quoting issues:
   ```bash
   cat > /tmp/relnotes.md <<'NOTES'
   ## <Title>

   ### What's new
   - ...

   ### Unchanged
   - ...
   NOTES
   ```

7. Create the release (tags the current branch HEAD; pass `--target` to be explicit). Add `--prerelease` for betas or `--draft` if the user wants to review on GitHub before it goes public:
   ```bash
   gh release create <vX.Y.Z> --target "$(git rev-parse --abbrev-ref HEAD)" \
     --title "<vX.Y.Z — short headline>" --notes-file /tmp/relnotes.md
   ```

8. Report the release URL:
   ```bash
   gh release view <vX.Y.Z> --json url -q .url
   ```

To attach build artifacts (e.g. a packaged ZIP), append their paths to the `gh release create` line or run `gh release upload <vX.Y.Z> <file> ...` afterward.
