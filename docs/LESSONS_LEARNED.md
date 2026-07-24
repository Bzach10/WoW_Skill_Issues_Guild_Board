# LESSONS_LEARNED.md — S.S. Wipe Fest

Running log of mistakes made and fixed, decisions that worked, and recurring failure
modes — so the project's knowledge compounds instead of getting lost. Maintained by the
scheduled knowledge-base task; anyone may add entries in the same format.

**Format per lesson: what happened → mechanism → cost → countermeasure.**

> Bootstrapped **2026-07-23** — this file did not previously exist. Seeded from git
> history (`2.0` through `a9c0a72`), `PROJECT_CONTEXT.md`, `docs/DEPLOYMENT.md`, and
> `OVERNIGHT_NOTES.md`. Every claim below is verified against the repo unless marked
> UNVERIFIED.

---

## LL-01 · Actions script injection via `${{ }}` in `run:` blocks (2026-07-22, fixed PR #2)

- **What happened:** `blizzard-profile-refresh.yml` spliced `github.event.inputs.force`
  and `github.ref_name` directly into `run:` script bodies. The `ref_name` splice sat in
  the step holding `GITHUB_TOKEN`. The security gate on the integration branch caught it.
- **Mechanism:** `workflow_dispatch` inputs are free text, and `${{ }}` is interpolated
  *before* the shell runs — so an input can become arbitrary command execution with that
  step's secrets.
- **Cost:** one failing security gate, one fix PR. Not exploited.
- **Countermeasure:** bind every template expression to an `env:` var and read it as
  `"$VAR"` inside the script — never splice. Pattern established in `weekly-board.yml`;
  enforced by `scripts/security_check.py --only actions`; the `security-reviewer` agent
  checks for it in every workflow diff.

## LL-02 · "Private" deploys weren't — preview URLs bypass the Access gate (2026-07-22)

- **What happened:** the production alias `skill-issues-board.pages.dev` returned a
  proper Cloudflare Access challenge, but the per-deployment hash URL printed by the very
  same `wrangler pages deploy` served the full site **unauthenticated**.
- **Mechanism:** a self-hosted Access application scoped to one hostname does not cover
  `<hash>.<project>.pages.dev` preview URLs, and Cloudflare keeps old ones live.
- **Cost:** near-miss — a link presumed private was public. Discovered only because it
  was actually tested instead of assumed.
- **Countermeasure:** `docs/DEPLOYMENT.md` §5 — never declare a link private without
  curling **both** the production alias **and** the exact preview URL of the latest
  deploy, after every deploy. The "Enable access policy" toggle is dashboard-only and
  remains Zach's to click. *Assume nothing about gating; verify each time.*

## LL-03 · A capability that lives in one session's memory is a capability the project loses (2026-07-22)

- **What happened:** Zach asked mid-deploy whether the Cloudflare deploy was documented
  anywhere. The honest answer was no.
- **Mechanism:** hand-run procedures accumulate inside a session and evaporate with it;
  the next session rediscovers them wrongly — or assumes they don't exist and redoes them
  badly. This is the project's defining failure mode (see `PROJECT_CONTEXT.md` §0: six
  widely-believed falsehoods each cost sessions).
- **Cost:** repeated rediscovery across the project's whole history.
- **Countermeasure:** write the operational doc **in the same session** that creates the
  capability (`docs/DEPLOYMENT.md` is the model). This knowledge base is the standing
  countermeasure.

## LL-04 · Separate "how to do it" from "it was done" (2026-07-23)

- **What happened:** the public-flip procedure (board public, `/review/*` stays gated)
  was written as a full checklist and explicitly labeled **"NOT executed, pending Zach's
  go-ahead"** (`docs/DEPLOYMENT.md` §2a, commit `89ef9a0`).
- **Mechanism (why this works):** docs that conflate procedure with completed state cause
  later sessions to assume states that don't exist — the exact class of error
  `PROJECT_CONTEXT.md` §0 catalogs.
- **Cost:** none — this one was done right; recorded as a pattern to repeat.
- **Countermeasure:** every procedure doc carries an execution-status label, and
  destructive/irreversible steps require an explicit go-ahead *in that session*.

## LL-05 · CI is not your laptop (2026-07-20; overnight iter 8)

- **What happened:** the Blizzard refresh Action failed because the repo root wasn't on
  `sys.path` in the runner (`bc521db`). Separately, `wcl.week_of` relied on
  function-local `datetime` imports — a latent `NameError` on a path only CI exercises
  (caught during overnight iteration 8).
- **Mechanism:** Actions runners differ in cwd/`sys.path`, and code paths exercised only
  in CI never run locally, so breakage stays invisible until the scheduled run.
- **Cost:** a broken scheduled workflow; silent until run day.
- **Countermeasure:** module-level imports; smoke-test the exact CI entry point from the
  repo root; keep the test suite offline and CI-identical (`pyproject.toml` pythonpath).

## LL-06 · Reposts inflated streaks — key week-over-week state to the raid week (2026-07-18/19)

- **What happened:** reposting the board counted the same raid week twice; attendance
  streaks, deltas, and NEW badges drifted (`a56f330`, `d45d789`, `3fe2fd2`).
- **Mechanism:** state was keyed to run time, not to the raid week — a repost looked like
  a new week.
- **Cost:** wrong numbers posted to the guild; a state migration to clean up.
- **Countermeasure:** all week-over-week state (streaks, deltas, badges) is keyed to the
  raid-week anchor (epoch 2026-07-14); each raid week counts **once**; tests pin it.

## LL-07 · Substring filters lie: "unholy" matched "holy" (`f13f836`)

- **Mechanism:** naive substring matching on role/spec names.
- **Cost:** wrong characters passed role filters.
- **Countermeasure:** whole-word matching for any role/spec/name filter, with boundary
  tests. Assume every substring match on game vocabulary is a bug until proven otherwise.

## LL-08 · Built ≠ wired (`02cf3d4`)

- **What happened:** the baseline view existed, tested, complete — and was never
  connected into `build_board`. Commit message: "the last missing connection."
- **Mechanism:** a feature finished in isolation; the integration point was nobody's
  explicit task; no end-to-end check existed to notice.
- **Cost:** a finished feature shipped nothing for days.
- **Countermeasure:** every feature gets an end-to-end wiring test (the guild-template
  module recipe test from overnight iter 9 is the model).

## LL-09 · Fail-open only counts if a test pins it (overnight iters 6 & 10; `160be7c`)

- **What happened:** the awards fail-open contract (a crashing award builder is skipped,
  the rest render) was pinned by test; the integrity layer validates and repairs data
  every build; missing theme assets heal to shipped defaults with a loud warning.
- **Mechanism:** fail-open behavior silently regresses unless a test actively breaks the
  component and asserts the build survives.
- **Cost:** none yet — preventive.
- **Countermeasure:** for every fail-open contract, a test that sabotages the component
  and asserts degraded-but-alive output. "Fails open" is a tested property, not a vibe.

## LL-10 · Alphabetical generation nearly burned the art budget (~2026-07-21)

- **What happened:** cast generation ran in name order at ~$0.40/character; spend went
  $8.38 → $10.90 in the time it took to write the alarm (`GENERATION_HANDOFF.md`).
  Ledger now: spent $10.90, **$0.46 left**.
- **Mechanism:** paid API + no priority ordering + no change detection = maximum spend
  for minimum visible value.
- **Cost:** most of the art budget, spent on the tail instead of the stars.
- **Countermeasure:** generate in priority order (season M+ > 1000 first); **always
  populate `transmog_fingerprint`** so unchanged characters are never re-billed; every
  costing subcommand requires an explicit flag — no accidental spend.

## LL-11 · OneDrive and git are hostile cohabitants (ongoing; checkpoint 2026-07-23)

- **What happened:** two git worktrees were destroyed when their `.git/worktrees/*`
  admin files vanished (30 MB each unreadable — consistent with OneDrive sync failure,
  `PROJECT_CONTEXT.md` §2.3). On 2026-07-23, after the pre-migration checkpoint
  (`a9c0a72`), the working tree shows **89 files of pure line-ending churn** (34,806
  insertions = 34,806 deletions; content byte-identical). Sandboxed sessions also hit an
  un-unlinkable `.git/index.lock` under the synced path.
- **Mechanism:** cloud sync races git's file operations, and CRLF/LF normalization
  differs across the tools touching this repo.
- **Cost:** lost worktrees, unreadable diffs, risk of committing 89-file noise commits.
- **Countermeasure:** the planned migration out of OneDrive (checkpoint committed and
  pushed 2026-07-23). At migration time: add a `.gitattributes` with an explicit eol
  policy. Meanwhile, treat any diff with equal insertions/deletions across whole files as
  line-ending noise — do not commit it as if it were content, and do not "fix" it file
  by file.

## LL-12 · Uncoordinated parallel sessions destroy work (2026-07-22 and before)

- **What happened:** `GuildBoardTrial\bounty\` (the only scripted part of the website)
  was deleted mid-scan by another session, with no record of whether its output was
  migrated; the website itself had **zero version control**; the project has repeatedly
  lost work to parallel sessions overwriting each other.
- **Mechanism:** multiple concurrent sessions with no shared in-flight ledger; deletions
  and rewrites happen without a survivable record; unversioned artifacts have no undo.
- **Cost:** unrecoverable scripts, re-derived decisions, an entire "Corrections" section
  in `PROJECT_CONTEXT.md`.
- **Countermeasure:** the operating rules in `PROJECT_CONTEXT.md` ("How we run this
  project"): read context first, sequence new work into `docs/STATUS.md`, nothing gets
  dropped without a status, update docs in the same session. Version-control everything
  that ships (git-init `GuildBoardTrial` remains open — `PROJECT_CONTEXT.md` §9.2).

---

*Add new lessons at the bottom with the next LL-number and the date. Refine or merge an
existing lesson if a new instance strengthens it — do not duplicate.*
