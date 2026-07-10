name: Weekly Guild Board

on:
  schedule:
    # Every Tuesday at 13:00 UTC (9 AM ET) — right before NA reset,
    # so it captures the full previous raid week.
    - cron: "0 13 * * 2"
  # This adds the "Run workflow" button so officers can post/repost
  # the board manually any time (e.g., after updating the roast).
  workflow_dispatch: {}

jobs:
  post-board:
    runs-on: ubuntu-latest
    steps:
      - name: Check out repo
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Build and post the board
        env:
          WCL_CLIENT_ID: ${{ secrets.WCL_CLIENT_ID }}
          WCL_CLIENT_SECRET: ${{ secrets.WCL_CLIENT_SECRET }}
          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
        run: python leaderboard.py
