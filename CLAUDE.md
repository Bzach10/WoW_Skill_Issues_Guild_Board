# Skill Issues Guild Board

Weekly WoW guild leaderboard: pulls raid/M+ data, renders a themed board
image + website, and posts it to Discord — all from GitHub Actions.

## Commands

```bash
python -m pytest -q                      # run tests (109+, no network needed)
python scripts/preview_board.py          # local preview with canned data, no API keys
python scripts/preview_board.py --png    # + Playwright screenshot (board_preview.png)
python -m ruff check .                   # lint (config in pyproject.toml)
```

On Windows, set `PYTHONIOENCODING=utf-8` before running scripts that print
board content — several names/strings are non-ASCII and the default console
codepage chokes on them.

## Deploy flow — everything posts from `main` via Actions

- `.github/workflows/weekly-board.yml` runs Tuesdays 13:00 UTC (pre-reset)
  and posts the board to Discord. `workflow_dispatch` supports overrides
  (roast, difficulty, lookback) and a `dry_run` input that skips the post.
- `board-vote.yml` and `blizzard-profile-refresh.yml` are the other two
  workflows. All secrets (Discord webhook, WCL, Blizzard) live in Actions;
  none exist locally.
- Local dev never posts to Discord. Use `scripts/preview_board.py` or the
  workflow's `dry_run` to test.

## CI-owned files — do not hand-edit

`board_state.json`, `roster_cache.json`, `weekly_state.json`,
`blizzard_profile_cache.json`, `data/accounts.json` and
`data/shares_ledger.json` are regenerated and committed by Actions with
`[skip ci]`. A PreToolUse hook blocks edits to them. Change the code that
produces them instead.

## THE SHIP'S ARTICLES — accounts (`guild_board/articles.py`)

Every share, card and board downstream is keyed on an ACCOUNT, not a
character. Members bind characters by typing `/claim <character>` in the
allowlisted claims channel; there is no live bot process, so a "slash
command" here is a MESSAGE the scheduled read picks up, exactly like the
roast ballot. `scripts/refresh_articles.py` is the **only** writer.

- **`data/accounts.json`** — the private ledger: `account_id →
  {characters, main, claimed_at}` plus a character index, an audit log and
  a message watermark. **No Discord id ever enters it.**
- **`web_data_public/articles.json`** — the public projection the site bakes:
  character key → `{account_id, is_main}`. Nothing else. An account's face on
  the site is its MAIN CHARACTER'S NAME — never a Discord handle.
- `account_id = HMAC-SHA256(ACCOUNTS_ID_SALT, discord_id)[:16]`. The salt is
  a secret with **no default**: without it the digest is reversible from the
  guild's member list, so the script refuses to write. Privacy fails CLOSED.
- `/revoke` is honoured only from a channel in `officer_channel_ids` — the
  channel's Discord permissions ARE the officer check, the same model
  `announcement_channel_id` already uses. No roles table.
- First claim wins; refusals are logged, never silent. A bare name that two
  roster characters share (there are two Berobens) is refused as ambiguous,
  never guessed.

`season_ledger/*.jsonl` and `data/seasons/**` are the same rule with a
stronger reason: the ledger is APPEND-ONLY and a freeze is written ONCE.
The hook blocks both directories.

## THE SHARES LEDGER — the currency (`guild_board/shares.py`)

> **PAY THE DEED, NEVER THE RANK.**

A published rate card, identical for every hand, paid for a thing you did.
Your payout never depends on another member's number. `RATE_CARD` is DATA —
eleven loops, each with a rate, a per-account weekly cap, a tier and (when it
pays nothing) the reason. Bump `RATE_CARD_VERSION` on any change; every
ledger row records the version that paid it.

- **The ladder is never a faucet.** `score`, `rank`, `ranks`, `top5`,
  `rankings`, `parse`, `percentile`, `standing`, `bounty` and the weekly
  deltas are named in `LADDER_FIELDS`, and
  `test_the_ladder_cannot_move_a_single_share` scrambles every one of them
  in the input bundle and asserts the ledger comes out identical. A grep
  would pass the moment one was read indirectly; a mutation cannot.
- **Every cap is per `account_id`**, summed over the characters signed under
  it. Alts change WHICH character earns, never HOW MUCH. An unsigned
  character is absent from `articles.json` and earns nothing.
- **Every share cites its deed.** `row_id = sha256(week|account|loop|deed_ref)`,
  so a share with no citation cannot be minted and re-running a week is a
  no-op instead of a second payment. **`data/shares_ledger.json` is
  append-only** — rows are never edited or removed.
- `balance = ledger rows − sinks`. Never stored; always recomputed from the
  citations, so it cannot drift from what justifies it.
- **Only T0/T1 loops pay.** T2 (needs Raider.io `run-details`, lane I4b-8)
  and T3 loops ship on the card priced at zero **with a stated reason**, so a
  loop that was deferred cannot be confused with a loop nobody thought of.
  **PvP pays nothing until seats are authenticated** — the Worker's seat
  identity is a client-typed slug, so a share off `/record` is a two-tab
  exploit.
- `scripts/refresh_shares.py` is the **only** writer. It needs no secret: it
  reads only bytes the pipeline already published. `web_data_public/shares.json`
  is the public projection; `articles.assert_opaque` runs on it and on the
  ledger before either becomes bytes, and `validate_bundle.check_shares`
  re-runs it on the emitted file.

## The season ledger and the season freeze

`guild_board/season_ledger.py` writes one compact line per character per
completed raid week to `season_ledger/<season-slug>.jsonl`, forever — the
series `board_state.json`'s two slots throw away every run. It is keyed on
`(season_slug, week_label, character_key)` and idempotent on that triple,
so both the daily refresh (`--append` step) and the Tuesday board post
(`main.py`, after `save_board_state`) can call it without coordinating.

```bash
python -m guild_board.season_ledger --dry-run       # what would be appended
python -m guild_board.season_ledger --append        # what CI runs daily
python -m guild_board.season_ledger --backfill      # reconstruct from git
python -m guild_board.season_ledger --freeze season-mn-1 [--source-rev SHA]
```

Rules that are not negotiable: rows key on `characters[].key` (name-realm)
— the roster holds two Berobens; `streak`/`attended` are `null` whenever
the evidence is missing or the week was never scanned, never `false`; a
week is only filed under the season it was played in; and `--freeze`
refuses to overwrite an existing `data/seasons/<slug>/` or to freeze from
a bundle of the wrong season's vintage. To redo a freeze, delete the
directory in a reviewed commit.

## Data sources

- **Raider.io** — no auth, works locally; treat it as ground truth when
  verifying member data.
- **Warcraft Logs (wcl.py)** and **Blizzard (blizzard.py)** — need
  credentials that exist only in CI. Code paths must stay inert/graceful
  when creds are absent.
- Player specs drift over time; don't hardcode spec expectations in tests.

## THE PAPER IS THE POST (`renderer:` in config.yml)

- `renderer: paper` (default, live): the weekly attachments are photographs
  of the website's newspaper at <https://skill-issues-board.pages.dev/board/>
  — page one, an above-the-fold teaser cut at the phone's measure, and page
  two's Season Ladder. `guild_board/paper_shot.py` drives it to the flat
  put-down edition (`data-paper=down` + `data-edition=spread`) and shoots.
  The site repo holds the original of that script
  (`wipefest-redesign/ops/press/post_front_page.py`); this is the vendored copy.
- `renderer: classic` parks the old path (below) unchanged.
- **The parity gate.** `parity_manifest.yml` lists every datum the board used
  to publish and where it now lives on the paper. `scripts/check_paper_parity.py`
  runs in the workflow BEFORE any secret is in the environment and refuses the
  post if one has vanished; `paper_shot` re-checks the rendered DOM.
  `tests/test_paper_post.py` runs the same check offline against
  `tests/fixtures/board_page_text.txt`. Fails CLOSED on parity, OPEN on a
  browser/network fault (the guild always gets a board).
- Dropping a datum on purpose = move its entry from `kept` to `dropped` with a
  reason. Never delete an entry to silence a failure.
- The week's own numbers (kills/pulls/wipes/deaths/keys/parses/improvement/roast)
  are persisted by `state.build_week_block` and delivered to the site as
  `weekly_board.json` (web_data → deliver_bundle → the paper's contract).

## Layout & theming (the `classic` renderer)

- Legacy layout is `image_board`, rendered via `guild_board/html_board.py`
  (Jinja2 templates in `guild_board/templates/`) and screenshotted with
  Playwright. `board_image.py` is the Pillow renderer.
- Visual knobs live in `theme.yml`; behavior/section knobs in `config.yml`.
- Design taste (see THEME_JOURNAL.md): rich art and real-paper texture,
  not flat dark panels or rigid grids.

## Testing & lint

- `pyproject.toml` sets `pythonpath = ["."]` because CI runs bare `pytest`.
- Tests must run offline — mock `requests`, never hit live APIs.
- Ruff runs automatically via a PostToolUse hook on every edited `.py`
  file; the repo is currently clean, keep it that way.
