# KNOWLEDGE_BASE.md — orientation index for S.S. Wipe Fest

A concise, current map of the project's key facts, decisions, and docs, so a new session
(or Zach) can get oriented fast. Maintained by the scheduled knowledge-base task.
**Last updated: 2026-07-23** (bootstrapped this date — file did not previously exist).

---

## What this project is, in three sentences

**S.S. Wipe Fest** is a One Piece–themed project for the WoW guild **Skill Issues**
(Bleeding Hollow US, cross-realm, ~130 rostered characters), owned by Zach (`Bzach10`).
It is **two artifacts tied by theming, not one**: (a) the **Discord board** — a Python
pipeline that posts a weekly status image every Tuesday (automated, live), and
(b) the **website** — a guild hangout/data site, deployed gated on Cloudflare Pages.
The #1 priority is the character showcase: anime-style art generated from members' real
WoW renders. Most historical confusion came from conflating (a) and (b) — always name
which one you mean.

## Read-first order for a cold session

1. `PROJECT_CONTEXT.md` (root) — canonical: what the project *is*, corrections to false
   beliefs, decisions log, constraints, punch list.
2. `docs/STATUS.md` — what is in flight *right now*.
3. `docs/LESSONS_LEARNED.md` — the failure modes you are about to repeat.
4. Whatever specialist doc the task touches (map below).

## Key facts (verified 2026-07-23)

- **Repo:** `github.com/Bzach10/WoW_Skill_Issues_Guild_Board`, private. Active branch
  **`2.0`** (in sync with origin as of `a9c0a72`); **`main` is frozen** for the live
  auto-post. Feature branches live in `C:\wt\*` worktrees (bdq, cg, fc, int, sec,
  datacorrect).
- **Cadence:** weekly is correct — Tuesday 13:00 UTC board post, 13:15 Blizzard refresh.
  Do not make it daily.
- **Realm rule (#1 bug class):** guild-level lookups use `bleeding-hollow`; every
  character lookup uses that character's OWN realm from its `name-realm` slug. 36
  distinct realms; 70% of members are NOT on Bleeding Hollow.
- **Two web presences, do not confuse:** the new gated site
  (`skill-issues-board.pages.dev`, Cloudflare Pages + Access, deployed by Wrangler
  Direct Upload from branch `frontend-crew-ui`) vs the old **public** weekly board
  (`bzach10.github.io/wow-guild-board`, GitHub Pages). `docs/DEPLOYMENT.md` §7 compares.
- **Gate verification is mandatory:** never call a deploy private without running
  `docs/DEPLOYMENT.md` §5 against the production alias AND the newest preview URL.
- **Public flip:** documented (`docs/DEPLOYMENT.md` §2a), **NOT executed** — needs
  Zach's explicit go-ahead.
- **Budget:** art ledger `spent_so_far: 10.901`, `budget_left_after: 0.46`
  (`ROSTER_PRIORITY.json`). Priority order + `transmog_fingerprint` are non-negotiable.
- **Secrets:** names in `PROJECT_CONTEXT.md` §4.2; never commit `.env`; never log
  values; `scripts/overnight/settings.py` is the only reader for the art pipeline.
- **Design principles:** fail open at every stage (tested, not assumed); looks
  (`theme.yml`) and data (`config.yml`) are separate files; empty-data states are a main
  path (26% of characters have no score); original characters only in generated art.

## State snapshot — 2026-07-23

- **Pre-migration checkpoint committed and pushed** on `2.0` (`a9c0a72`) and on each
  worktree branch ("Pre-migration checkpoint (bdq/cg/fc/int/sec…)"). The planned
  migration out of OneDrive (to `C:\dev\…`) has **NOT happened yet** — this OneDrive
  copy is still the live repo. No `DEV_WORKFLOW.md` exists yet.
- **Working tree:** 89 modified files that are pure line-ending churn (equal
  insertions/deletions, byte-identical content) — see LL-11. Do not commit as content.
- **Recent lands (Jul 22–23):** Claude Code automations (CLAUDE.md, hooks, skills,
  agents, ruff); workflow-injection fix (PR #2); `docs/DEPLOYMENT.md` written and
  refined; public-flip procedure documented.
- **Recent lands (Jul 18–21):** redesign pass (3 new layouts + 4 themes + preview
  matrix); Imperial Bounty ink-on-paper theme; Blizzard character-profile integration;
  Voyage Map data model; raid-week anchoring for streaks/deltas; self-healing integrity
  layer; overnight iterations 1–10 (~100 tests green at iter 10).

## Doc map

| Doc | What it holds |
|---|---|
| `PROJECT_CONTEXT.md` | Canonical context. Corrections (§0), file map, architecture, decisions log, constraints, punch list. |
| `docs/STATUS.md` | Living in-flight ledger (Working / To Do / Ideas / Back Burner / Archive). |
| `docs/LESSONS_LEARNED.md` | Failure modes and countermeasures, LL-numbered. |
| `docs/DEPLOYMENT.md` | Cloudflare Pages deploy + Access gate + verification + public-flip checklist (§2a, not executed). |
| `docs/KNOWLEDGE_BASE.md` | This file. |
| `CLAUDE.md` | Claude Code automation entry point (hooks, skills, agents live under `.claude/`). |
| `CUSTOMIZING.md` | Non-coder guide to theme/board knobs. |
| `REDESIGN_NOTES.md` | Catalogue of the 3 new web layouts + 4 themes; what's real vs fixture in previews. |
| `OVERNIGHT_NOTES.md` | Log of the overnight hardening iterations 1–10. |
| `THEME_JOURNAL.md` | Theme history and art-direction notes. |
| `GENERATION_HANDOFF.md` | Cast-generation operations: cost rules, priority tiers, fingerprint requirement. |
| `ENGINE_INTERFACE.md` | Generation-engine contract (swappable backend); LoRA migration risk. |
| `HANGOUT_DESIGN.md` | Website/ship design spec (11 rooms, Discord integration scope, privacy rules). |
| `LAYER_CONTRACT_frontend.md` | Paper-doll layer z-stack contract (pipeline benched, contract still authoritative for those assets). |
| `SCENE_SCENARIOS.md` | The 12 backdrop scenes + casting rules. |
| `TRIAL_HANDOFF.md` / `WEBSITE_IDEAS.md` / `IDEAS_BACKLOG.md` | Trial handoff notes; site ideas; backlog (NFT explicitly killed). |
| `SETUP_BLIZZARD.md` | Blizzard API credential setup. |
| `windows-cheatsheet.md` | PowerShell-vs-bash pitfalls for sessions on this machine. |

## Known drift / open questions (flagged, not silently fixed)

1. **`C:\wt\fc` — does it exist right now?** `PROJECT_CONTEXT.md` §2.3 (snapshot 07-22
   01:40) says the `C:\wt\*` worktrees no longer exist on disk; `docs/DEPLOYMENT.md`
   (written 07-22 evening) uses `C:\wt\fc` as the live deploy source, and git shows a
   `datacorrect` worktree branch dated 07-23. Most likely the worktrees were recreated
   after the snapshot. Unverifiable from a sandbox (git reports all worktrees
   "prunable" there because `C:\wt` isn't mounted). **Needs a host-session check.**
2. **The ~67 generated characters' art** — referenced in `GENERATION_HANDOFF.md`,
   previously tied to `C:\wt\fc`. Whereabouts still UNVERIFIED (`PROJECT_CONTEXT.md`
   §9.12). Worth resolving before the migration, at ~$9 regeneration risk.
3. **`PROJECT_CONTEXT.md` §9.5** says `2.0` is "8 ahead / 4 behind origin with 165 dirty
   files" — now stale: `2.0` is in sync with origin as of `a9c0a72`, and the current
   dirt is the 89-file line-ending churn. Left in place because §9 is a dated snapshot;
   noted here instead.
4. **Discord bot token in plaintext OneDrive file** (`PROJECT_CONTEXT.md` §9.1) — no
   evidence in the repo that rotation happened. Still open as far as docs show.
5. **`docs/STATUS.md` did not exist until 2026-07-23** despite being load-bearing in
   `PROJECT_CONTEXT.md`'s operating rules. A bootstrap version now exists — it needs
   Zach (or the next working session) to confirm/correct the in-flight list.
