---
name: board-dryrun
description: Trigger the Weekly Guild Board workflow on GitHub Actions in dry-run mode (builds the real board with real data but does not post to Discord) and watch it to completion.
disable-model-invocation: true
---

# Dry-run the weekly board pipeline

Run the full production pipeline — real API data, real rendering — without
posting to Discord.

## Steps

1. Dispatch the workflow with `dry_run` set:

   ```bash
   gh workflow run weekly-board.yml --ref main -f dry_run=true
   ```

   If the user passed overrides (e.g. `difficulty=heroic lookback=14`),
   forward each as an extra `-f key=value`. Valid inputs: `roast`,
   `roast_winner`, `roast_target`, `difficulty`, `lookback`.

2. Wait a few seconds for the run to register, then grab its id:

   ```bash
   gh run list --workflow=weekly-board.yml --limit 1 --json databaseId,status,createdAt
   ```

   Sanity-check `createdAt` is from just now (not a stale run).

3. Watch it to completion:

   ```bash
   gh run watch <run-id> --exit-status
   ```

4. Report the outcome. On failure, pull the failing step's log with
   `gh run view <run-id> --log-failed` and summarize the actual error —
   don't just say it failed.

Notes: the dispatch runs on `main`, not the local branch — local uncommitted
changes are not exercised. This triggers real API calls in CI; that's the
point, but don't spam repeat runs while one is already in progress.
