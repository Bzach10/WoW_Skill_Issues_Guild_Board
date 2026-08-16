"""THE PAPER IS THE POST -- shoot the live newspaper for the weekly dispatch.

The board used to render its own image from its own templates. The website
now prints the same guild, the same week and the same numbers as a
four-page newspaper, so a second board is a second composition that can
drift from the first. This module replaces the render with a photograph of
the paper itself:

    weekly_post_front.png    page one, whole
    weekly_post_fold.png     above the fold, at the phone's own measure --
                             the teaser Discord shows at embed width
    weekly_post_ladder.png   page two, the Season Ladder, whole

It is the SAME shot the site repo takes (ops/press/post_front_page.py);
this is the vendored copy so the workflow needs nothing but the site's
public URL. When the two ever disagree, the site's copy is the original.

THE STATE IT SHOOTS is the flat put-down edition: `data-paper="down"`
(the sheet lying in the world, at the held footprint, every animation stood
down) plus `data-edition="spread"` so all four leaves print and each can be
bounded on its own.

THE PARITY GATE runs here, before anything is posted: parity_manifest.yml
lists every datum the paper is required to still be carrying, and
`check_parity` reads the fetched page and refuses the post -- loudly -- if
one has vanished. A silently emptier paper is the one failure mode this
swap introduces, so it is the one thing that is measured every week.

Fails CLOSED on the parity gate (a paper missing a kept datum must not be
posted) and OPEN on everything else (a browser fault falls back to the
classic renderer rather than skipping the week).
"""

import hashlib
import io
import json
import logging
import os
import re
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

BOARD_URL = "https://skill-issues-board.pages.dev/board/"
MANIFEST_FILE = "parity_manifest.yml"

SHEET_W, SHEET_H, SHEET_DSF = 1560, 1200, 2
PHONE_W, PHONE_H, PHONE_DSF = 430, 932, 3
FOLD_MAX_ASPECT = 1.35
# Discord refuses an attachment over 10 MiB on a free guild, and an
# attachment that will not upload is the same as no post at all.
BUDGET = 8 * 1024 * 1024
STEPS = (1.0, 0.8, 0.65, 0.5)

SETTLE = """async () => {
  document.querySelectorAll('img[loading="lazy"]').forEach(i => {
    i.loading = 'eager';
    if (i.dataset && i.dataset.src && !i.src) { i.src = i.dataset.src; }
  });
  const imgs = [].slice.call(document.images);
  await Promise.all(imgs.map(i => i.complete ? null : new Promise(r => {
    i.addEventListener('load', r, { once: true });
    i.addEventListener('error', r, { once: true });
  })));
  if (document.fonts && document.fonts.ready) { await document.fonts.ready; }
  return imgs.length;
}"""

PUT_DOWN = """() => {
  const r = document.documentElement;
  r.setAttribute('data-paper', 'down');
  r.setAttribute('data-edition', 'spread');
  const deck = document.getElementById('deck');
  if (deck) { deck.hidden = true; }
  return { paper: r.getAttribute('data-paper'),
           edition: r.getAttribute('data-edition'),
           leaves: document.querySelectorAll('.paper-table .paper-page').length };
}"""

FOLD_BOX = r"""() => {
  const leaf = document.querySelector('.paper-page[data-page-n="1"]');
  if (!leaf) { return null; }
  const lb = leaf.getBoundingClientRect();
  const co = leaf.querySelector('hr.cutoff');
  const head = leaf.querySelector('.lead__head');
  const units = [];
  leaf.querySelectorAll('.mh__rule, .lead__kicker, .lead__head, .lead__bank,'
    + ' .lead__fig, .lead__byline, .lead__body > p, .cutline, .newsbrief__h,'
    + ' .newsbrief__b, .jimdash, figure.cut').forEach(el => {
    if (!el.offsetWidth) { return; }
    units.push(Math.round(el.getBoundingClientRect().bottom + scrollY));
  });
  return {
    leaf: [lb.left + scrollX, lb.top + scrollY, lb.width, lb.height],
    cutoff: co ? (co.getBoundingClientRect().bottom + scrollY) : null,
    units: units.sort((a, b) => a - b),
    headText: head ? (head.textContent || '').replace(/\s+/g, ' ').trim() : '',
    headFS: head ? parseFloat(getComputedStyle(head).fontSize) : 0
  };
}"""

PAGE_TEXT = """() => {
  const t = document.querySelector('main') || document.body;
  return (t.innerText || '').replace(/\\s+/g, ' ');
}"""


def _record_browser_error(errors, message):
    """Keep hostile page output from becoming Actions workflow commands."""
    if len(errors) >= 20:
        return
    safe = str(message).replace("%", "%25").replace("\r", "%0D").replace(
        "\n", "%0A")
    errors.append(safe[:500])


# ---------------------------------------------------------------------------
# The parity gate
# ---------------------------------------------------------------------------

def load_parity_manifest(path=MANIFEST_FILE):
    """The kept-datum manifest, or None when it is not checked in."""
    import yaml
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return None


def check_parity(page_text, manifest):
    """Every KEPT datum still on the paper?

    Each entry names a datum, the page it lives on, the DOM anchor a proof
    can bound it with, and one or more `expect` patterns -- case-insensitive
    regexes matched against the paper's own rendered text. A datum whose
    `expect` no longer matches has left the sheet, and this is the only
    place that would notice.

    Entries marked `pending: true` are berths that print a seam until the
    ingestion feeds them; their absence is not a regression, so they are
    reported and not enforced.

    Returns (missing, checked) -- `missing` is the list of enforced entries
    that failed.
    """
    text = (page_text or "")
    missing, checked = [], 0
    for entry in (manifest or {}).get("kept") or []:
        patterns = entry.get("expect") or []
        if isinstance(patterns, str):
            patterns = [patterns]
        if not patterns:
            continue
        checked += 1
        hit = all(re.search(p, text, re.I | re.S) for p in patterns)
        if hit:
            continue
        if entry.get("pending"):
            logger.info("PARITY (pending, not enforced): %s -- %s",
                        entry.get("datum"), entry.get("note", ""))
            continue
        missing.append(entry)
    return missing, checked


def check_freshness(page_text, expected_week, expected_weekly=None):
    """Return whether the paper identifies the week this run is posting.

    The consumer is deployed independently, so structural parity alone can
    pass against an old edition. Accept the contract's ISO label or the
    human-readable newspaper date, and reject an otherwise valid stale page.
    """
    if not expected_week:
        return True
    try:
        week = date.fromisoformat(str(expected_week))
    except (TypeError, ValueError):
        return False
    human = f"{week.strftime('%B')} {week.day}, {week.year}"
    text = page_text or ""
    if not (str(expected_week).lower() in text.lower()
            or human.lower() in text.lower()):
        return False
    # A week label remains unchanged for seven days, so it cannot distinguish
    # Tuesday morning's pending paper from the newly posted weekly contract.
    # Pulls/wipes are uniquely weekly figures on the paper and close that gap.
    weekly = expected_weekly or {}
    for label in ("pulls", "wipes"):
        value = weekly.get(label)
        if value is None:
            continue
        patterns = (
            rf"\b{re.escape(str(value))}\s+{label}\b",
            rf"\b{label}\s*:?\s*{re.escape(str(value))}\b",
        )
        if not any(re.search(pattern, text, re.I) for pattern in patterns):
            return False
    return True


# ---------------------------------------------------------------------------
# The shot
# ---------------------------------------------------------------------------

def _fit(path):
    """Step the capture down until Discord will take it."""
    from PIL import Image
    path = Path(path)
    if path.stat().st_size <= BUDGET:
        return 1.0
    with Image.open(path) as im:
        base = im.convert("RGB")
        for step in STEPS[1:]:
            small = base.resize((max(1, int(base.width * step)),
                                 max(1, int(base.height * step))),
                                Image.LANCZOS)
            small.save(path, optimize=True)
            if path.stat().st_size <= BUDGET:
                return step
    return STEPS[-1]


def _meta(path):
    from PIL import Image
    path = Path(path)
    with Image.open(path) as im:
        w, h = im.size
    return {"file": path.name, "path": str(path), "px": [w, h],
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _open_flat(ctx, url, errors):
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: _record_browser_error(
        errors, f"pageerror: {e}"))
    pg.on("console", lambda m: _record_browser_error(errors, m.text)
          if m.type == "error" else None)
    sep = "&" if "?" in url else "?"
    pg.goto(url + sep + "edition=spread", wait_until="networkidle", timeout=90_000)
    state = pg.evaluate(PUT_DOWN)
    pg.wait_for_timeout(900)
    pg.evaluate(SETTLE)
    pg.wait_for_timeout(500)
    return pg, state


def shoot_paper(url=None, out_dir=".", manifest=None, expected_week=None,
                expected_weekly=None):
    """Shoot the paper and gate it. Returns a dict, or None if it cannot.

    dict keys: front, fold, ladder (paths), manifest (dict), parity
    (dict with missing/checked/enforced). Raises ParityFailure when a kept
    datum has vanished -- that one is deliberately not survivable.
    """
    from PIL import Image
    from playwright.sync_api import sync_playwright

    url = url or os.environ.get("PAPER_BOARD_URL") or BOARD_URL
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    errors, shots, fold_note = [], {}, {}
    page_text = ""

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            ctx = browser.new_context(viewport={"width": SHEET_W, "height": SHEET_H},
                                      device_scale_factor=SHEET_DSF)
            pg, state = _open_flat(ctx, url, errors)
            if state.get("paper") != "down" or not state.get("leaves"):
                raise RuntimeError(f"the paper never went down at {url} ({state})")
            page_text = pg.evaluate(PAGE_TEXT)
            if not check_freshness(page_text, expected_week, expected_weekly):
                raise StalePaperError(
                    f"paper at {url} does not identify expected week "
                    f"{expected_week}; use the fresh classic render")
            for n, key, name in ((1, "front", "weekly_post_front.png"),
                                 (2, "ladder", "weekly_post_ladder.png")):
                sel = f'.paper-table .paper-page[data-page-n="{n}"]'
                leaf = pg.locator(sel)
                if not leaf.count():
                    raise RuntimeError(f"no leaf {n} at {url}")
                dest = out / name
                leaf.first.screenshot(path=str(dest), timeout=60_000)
                _fit(dest)
                shots[key] = _meta(dest)
            ctx.close()

            ctx = browser.new_context(viewport={"width": PHONE_W, "height": PHONE_H},
                                      device_scale_factor=PHONE_DSF, has_touch=True)
            pgm, statem = _open_flat(ctx, url, errors)
            if statem.get("paper") != "down":
                raise RuntimeError("the phone's paper never went down")
            box = pgm.evaluate(FOLD_BOX)
            if not box:
                raise RuntimeError("page one is not on the phone's sheet")
            lx, ly, lw, lh = box["leaf"]
            limit = ly + FOLD_MAX_ASPECT * lw
            fold = box["cutoff"] or limit
            bounded = min(fold, limit, ly + lh)
            whole = [u for u in (box["units"] or []) if u <= bounded]
            if whole and bounded < fold:
                bounded = max(whole)
            dest = out / "weekly_post_fold.png"
            buf = pgm.locator(
                '.paper-table .paper-page[data-page-n="1"]').first.screenshot(timeout=60_000)
            with Image.open(io.BytesIO(buf)) as im:
                cut = max(int(round((bounded - ly) * PHONE_DSF)), 240)
                im.convert("RGB").crop((0, 0, im.width,
                                        min(cut, im.height))).save(dest)
            _fit(dest)
            shots["fold"] = _meta(dest)
            fold_note = {"cut_at": round(bounded - ly, 1),
                         "fold_rule_at": (round(box["cutoff"] - ly, 1)
                                          if box["cutoff"] else None),
                         "headline": box["headText"][:120],
                         "headline_px": box["headFS"]}
            ctx.close()
        finally:
            browser.close()

    parity = {"checked": 0, "missing": [], "enforced": manifest is not None}
    if manifest is not None:
        missing, checked = check_parity(page_text, manifest)
        parity["checked"] = checked
        parity["missing"] = [m.get("datum") for m in missing]
        if missing:
            for m in missing:
                logger.error("PARITY FAILURE: '%s' is no longer on the paper "
                             "(page %s, anchor %s) -- expected %s",
                             m.get("datum"), m.get("page"), m.get("anchor"),
                             m.get("expect"))
            raise ParityFailure(
                f"{len(missing)} kept datum(s) vanished from {url}: "
                + ", ".join(parity["missing"]))
    else:
        logger.warning("No %s checked in -- the paper is being posted "
                       "UNGATED.", MANIFEST_FILE)

    out_manifest = {"url": url, "state": {"data-paper": "down",
                                          "data-edition": "spread"},
                    "fold": fold_note, "console_errors": errors,
                    "parity": parity, "shots": shots}
    (out / "weekly_post.json").write_text(json.dumps(out_manifest, indent=1),
                                          encoding="utf-8")
    if errors:
        logger.warning("The paper logged %d console error(s): %s",
                       len(errors), errors[:3])
    logger.info("Paper shot: front %s, fold %s, ladder %s (parity: %d datum(s) checked)",
                shots["front"]["px"], shots["fold"]["px"], shots["ladder"]["px"],
                parity["checked"])
    return {"front": shots["front"]["path"], "fold": shots["fold"]["path"],
            "ladder": shots["ladder"]["path"], "manifest": out_manifest,
            "parity": parity}


class ParityFailure(RuntimeError):
    """A datum the paper is required to carry is no longer on it."""


class StalePaperError(RuntimeError):
    """The paper is structurally valid but belongs to an older week."""
