# STATUS.md — what is in flight

The living ledger `PROJECT_CONTEXT.md`'s operating rules require. Statuses: **Working /
To Do / Ideas / Back Burner / Archive**. Nothing gets dropped — it gets a status and a
reason.

> ⚠ **Bootstrapped 2026-07-23 by the scheduled knowledge-base task.** This file was
> referenced by `PROJECT_CONTEXT.md` but did not exist. Items below are reconstructed
> from git history and docs, not from a working session's own knowledge — the next
> working session should confirm, correct, and take ownership of this file. Update it
> in the same session you finish work.

## Working

- **Repo migration out of OneDrive** (to `C:\dev\…`). Pre-migration checkpoint
  `a9c0a72` committed and pushed on `2.0` and every worktree branch (2026-07-23
  evening). The move itself has not happened yet — this OneDrive copy is still live.
  On completion: update `PROJECT_CONTEXT.md` §2.1 paths, add `.gitattributes` eol
  policy (see LL-11), and record the new root in `docs/KNOWLEDGE_BASE.md`.

## To Do (evidence of being queued, not started)

- **Public flip** — make the board public, keep `/review/*` gated. Fully documented in
  `docs/DEPLOYMENT.md` §2a. **Blocked on: Zach's explicit go-ahead.**
- **"Enable access policy" toggle** on the Pages project (per-deployment preview URLs).
  Dashboard-only; Zach's to click. `docs/DEPLOYMENT.md` §2.
- **Rotate the Discord bot token** sitting in plaintext in OneDrive
  (`PROJECT_CONTEXT.md` §9.1). No evidence of rotation in the repo yet.
- **Redesign vote** — layouts/themes built and previewed (`REDESIGN_NOTES.md`,
  `redesign_previews/`), vote workflow exists; the vote itself unfired per commit
  `97c1939`.
- **Apply `ANIMATION_FIX.md`** (complete, not applied — `PROJECT_CONTEXT.md` §9.10).
- **Resolve the ~67 generated characters' whereabouts** before migration
  (`PROJECT_CONTEXT.md` §9.12; ~$9 regeneration risk).
- **`git init` the website** (`GuildBoardTrial`) — still unversioned per
  `PROJECT_CONTEXT.md` §9.2.
- **Add confirmation input to `board-vote.yml`** (one-click posts to an unconfirmed
  webhook channel — `PROJECT_CONTEXT.md` §7.9).

## Ideas / Back Burner / Archive

- See `IDEAS_BACKLOG.md` and `PROJECT_CONTEXT.md` §6 for the authoritative feature
  table (Discord chat integration and chat-derived short stories are **planned, named
  by Zach**; paper-doll rig **benched**; NFT **killed**).

---

*Last touched: 2026-07-23 (knowledge-base task bootstrap).*
