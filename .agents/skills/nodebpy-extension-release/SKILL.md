---
name: nodebpy-extension-release
description: Release and website-publishing workflow for the local nodebpy_extension Blender add-on. Use when Codex is asked to make a new nodebpy_extension release, bump its Blender manifest version, push a GitHub release tag, update the nodebpy extension blog page, or remember where the related website repo and blog post live.
---

# Nodebpy Extension Release

## Overview

Use this skill to avoid rediscovering the release and website wiring for the
`nodebpy_extension` project.

## Known Repositories

- Add-on repo: `/Users/jan-hendrik/projects/nodebpy_extension`
- Add-on GitHub repo: `https://github.com/kolibril13/nodebpy_extension`
- Website repo: `/Users/jan-hendrik/projects/jan-hendrik-mueller.de`
- Blog post source: `src/content/blog/nodebpy-extension.md`
- Published blog URL: `https://jan-hendrik-mueller.de/blog/nodebpy-extension/`

## Release Workflow

1. Check both worktrees with `git status --short --branch`.
2. In the add-on repo, bump `nodebpy_export/blender_manifest.toml`.
3. Run local checks that do not require Blender:
   - `python3 -m compileall -q nodebpy_export`
   - `git diff --check`
4. Commit the add-on changes on `main`.
5. Create and push a matching release tag, for example `v0.1.5`.
6. The `.github/workflows/release.yml` workflow builds the extension with
   Blender, creates the GitHub Release, uploads the zip, and triggers the
   website rebuild hook when `CF_DEPLOY_HOOK_URL` is configured.
7. Use `gh run list --workflow release.yml` and `gh run watch <run-id>` to
   verify the release workflow.

If Blender is unavailable locally, rely on the GitHub Actions workflow for
`blender --command extension validate` and extension packaging, but say so in
the final status.

## Website Update Workflow

The blog post embeds a drag-and-drop extension card and dynamically refreshes
version/archive data from `/blender-extensions/index.json`. Keep the static
fallback values reasonably current when making a release.

When asked to add or fix the source link, edit
`/Users/jan-hendrik/projects/jan-hendrik-mueller.de/src/content/blog/nodebpy-extension.md`
and point to `https://github.com/kolibril13/nodebpy_extension`.

Useful website checks:

- `npm run build`
- `git diff --check`

The site prebuild fetches latest GitHub release data for
`kolibril13/nodebpy_extension`, so a successful add-on release should become
visible after the website rebuild.
