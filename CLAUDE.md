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

- `.github/workflows/weekly-board.yml` runs Tuesdays 16:00 UTC (post-reset)
  and posts the board to Discord. `workflow_dispatch` supports overrides
  (roast, difficulty, lookback) and a `dry_run` input that skips the post.
- `board-vote.yml` and `blizzard-profile-refresh.yml` are the other two
  workflows. All secrets (Discord webhook, WCL, Blizzard) live in Actions;
  none exist locally.
- Local dev never posts to Discord. Use `scripts/preview_board.py` or the
  workflow's `dry_run` to test.

## CI-owned files — do not hand-edit

`board_state.json`, `roster_cache.json`, `weekly_state.json`, and
`blizzard_profile_cache.json` are regenerated and committed by Actions with
`[skip ci]`. A PreToolUse hook blocks edits to them. Change the code that
produces them instead.

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
