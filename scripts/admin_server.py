#!/usr/bin/env python3
"""LOCAL-ONLY admin panel for the guild board.

    python scripts/admin_server.py        # opens http://127.0.0.1:8765

Zach's private control panel: pick the month's scene, the default theme,
tune the backdrop scrim, and reorder / hide the page sections — with a
live preview beside the controls. Save writes config.yml and re-renders.

This is a development tool. It binds to localhost only, and it is never
part of the published build — nothing in the bundle references it.
"""

import argparse
import json
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from guild_board import admin_config, scenery  # noqa: E402

PREVIEW = ROOT / "trial.html"
CREW_LIMIT = 40          # a lighter preview re-renders fast


def render_preview():
    """Re-render the board so the preview reflects saved config."""
    result = subprocess.run(
        [sys.executable, "scripts/render_crew_board.py",
         "--crew-limit", str(CREW_LIMIT)],
        cwd=ROOT, capture_output=True, text=True)
    return result.returncode == 0, (result.stderr or result.stdout)[-2000:]


def _page():
    scenes = sorted(scenery.available())
    settings = admin_config.current_settings()
    months = [(i, ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][i - 1])
              for i in range(1, 13)]
    return ADMIN_HTML.replace("__SCENES__", json.dumps(scenes)) \
                     .replace("__SETTINGS__", json.dumps(settings)) \
                     .replace("__MONTHS__", json.dumps(months)) \
                     .replace("__SECTIONS__", json.dumps(
                         [[k, admin_config.SECTION_LABELS[k]]
                          for k in admin_config.SECTIONS]))


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_):
        pass

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._send(200, _page())
        if path == "/api/settings":
            return self._send(200, json.dumps(admin_config.current_settings()),
                              "application/json")
        if path in ("/preview", "/preview.html"):
            if PREVIEW.exists():
                return self._send(200, PREVIEW.read_bytes(), "text/html; charset=utf-8")
            return self._send(404, "no preview yet — save once")
        # serve referenced local assets for the preview iframe
        candidate = (ROOT / path.lstrip("/")).resolve()
        try:
            candidate.relative_to(ROOT)
        except ValueError:
            return self._send(403, "forbidden")
        if candidate.is_file():
            ctype = ("image/png" if candidate.suffix == ".png"
                     else "image/jpeg" if candidate.suffix in (".jpg", ".jpeg")
                     else "text/html; charset=utf-8" if candidate.suffix == ".html"
                     else "application/octet-stream")
            return self._send(200, candidate.read_bytes(), ctype)
        return self._send(404, "not found")

    def do_POST(self):
        if urlparse(self.path).path != "/api/save":
            return self._send(404, "not found")
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or "{}")
        except ValueError:
            return self._send(400, json.dumps({"ok": False, "error": "bad json"}),
                              "application/json")
        saved = admin_config.save(payload)
        ok, log = render_preview()
        return self._send(200, json.dumps({"ok": ok, "settings": saved, "log": log}),
                          "application/json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    # ensure there is a preview to show before the first save
    if not PREVIEW.exists():
        print("rendering an initial preview…")
        render_preview()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Guild Board admin panel — LOCAL ONLY — {url}")
    print("This tool is not part of the published build. Ctrl-C to stop.")
    if not args.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Guild Board — Admin (local)</title>
<style>
  :root{--bg:#15101d;--panel:#20182c;--line:#3a2e4a;--text:#efe7f5;--muted:#a99cc0;--accent:#d8a24a;}
  *{box-sizing:border-box;margin:0;padding:0;}
  body{background:var(--bg);color:var(--text);font:15px/1.5 system-ui,sans-serif;
    display:grid;grid-template-columns:360px 1fr;height:100vh;overflow:hidden;}
  .panel{padding:18px;overflow-y:auto;border-right:1px solid var(--line);}
  .panel h1{font-size:16px;letter-spacing:.04em;margin-bottom:2px;}
  .panel .sub{color:var(--muted);font-size:12px;margin-bottom:16px;}
  .local{display:inline-block;font-size:10px;letter-spacing:.14em;text-transform:uppercase;
    background:var(--accent);color:#1a1020;padding:3px 9px;border-radius:999px;margin-bottom:14px;}
  fieldset{border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-bottom:14px;}
  legend{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);padding:0 6px;}
  label{display:block;font-size:12px;color:var(--muted);margin:8px 0 4px;}
  select,input[type=range]{width:100%;}
  select{background:var(--panel);color:var(--text);border:1px solid var(--line);
    border-radius:8px;padding:7px 9px;font:inherit;}
  .themes,.rowbtns{display:flex;gap:6px;flex-wrap:wrap;}
  .themes button{flex:1;padding:8px;border-radius:8px;border:1px solid var(--line);
    background:var(--panel);color:var(--text);cursor:pointer;font:inherit;font-size:12px;}
  .themes button.on{background:var(--accent);color:#1a1020;border-color:var(--accent);}
  .seclist{list-style:none;}
  .seclist li{display:flex;align-items:center;gap:8px;padding:6px 8px;margin:5px 0;
    background:var(--panel);border:1px solid var(--line);border-radius:8px;font-size:13px;}
  .seclist li.off{opacity:.45;}
  .seclist .grip{color:var(--muted);cursor:default;}
  .seclist .nm{flex:1;}
  .seclist button{background:none;border:1px solid var(--line);color:var(--text);
    border-radius:6px;width:26px;height:26px;cursor:pointer;font-size:13px;}
  .scrimval{color:var(--accent);font-weight:700;}
  .save{width:100%;padding:12px;border-radius:10px;border:0;background:var(--accent);
    color:#1a1020;font-weight:700;font-size:14px;cursor:pointer;margin-top:6px;}
  .save:disabled{opacity:.6;}
  .status{font-size:12px;color:var(--muted);margin-top:8px;min-height:1.4em;}
  .preview{position:relative;}
  .preview iframe{width:100%;height:100%;border:0;background:#fff;}
  .pvbar{position:absolute;top:0;left:0;right:0;display:flex;gap:8px;align-items:center;
    padding:8px 12px;background:rgba(21,16,29,.9);font-size:12px;color:var(--muted);z-index:2;}
  .pvbar span{margin-left:auto;}
</style></head>
<body>
<div class="panel">
  <span class="local">Local only · not published</span>
  <h1>Board Admin</h1>
  <p class="sub">Changes preview live. Save writes config.yml.</p>

  <fieldset><legend>Theme</legend>
    <div class="themes" id="themes">
      <button data-theme="codex">Codex</button>
      <button data-theme="console">Console</button>
      <button data-theme="chronicle">Chronicle</button>
    </div>
  </fieldset>

  <fieldset><legend>This month's scene</legend>
    <label>July (current month)</label>
    <select id="scene"></select>
  </fieldset>

  <fieldset><legend>Backdrop scrim</legend>
    <label>Atmosphere strength — <span class="scrimval" id="scrimval"></span></label>
    <input type="range" id="scrim" min="80" max="99" step="1">
    <p class="sub" style="margin:6px 0 0;">Higher = subtler backdrop, more readable.</p>
  </fieldset>

  <fieldset><legend>Sections — drag order, toggle off</legend>
    <ul class="seclist" id="sections"></ul>
  </fieldset>

  <button class="save" id="save">Save &amp; re-render</button>
  <div class="status" id="status"></div>
</div>

<div class="preview">
  <div class="pvbar">Live preview <span id="pvnote">local</span></div>
  <iframe id="pv" src="/preview"></iframe>
</div>

<script>
var SCENES = __SCENES__, MONTHS = __MONTHS__, SECTIONS = __SECTIONS__;
var S = __SETTINGS__;
var pv = document.getElementById('pv');

function post(fn){ try{ fn(pv.contentDocument, pv.contentWindow); }catch(e){} }

// live preview helpers — instant, no re-render
function applyTheme(t){ post(function(d){ if(d&&d.documentElement) d.documentElement.setAttribute('data-crew-theme', t); }); }
function applyScrim(v){ post(function(d){ var b=d&&d.querySelector('.backdrop::after'); });
  // scrim needs a CSS var; inject a style override into the iframe
  post(function(d){ if(!d) return; var id='scrimOverride', st=d.getElementById(id);
    if(!st){ st=d.createElement('style'); st.id=id; d.head.appendChild(st); }
    st.textContent='.backdrop::after{background:color-mix(in srgb,var(--bg) '+v+'%,transparent)!important;}'; });
}
function applyHidden(){ post(function(d){ if(!d) return;
  SECTIONS.forEach(function(pair){ var el=d.querySelector('[data-section="'+pair[0]+'"]');
    if(el) el.style.display = S.hidden.indexOf(pair[0])!==-1 ? 'none':''; }); }); }
function applyOrder(){ post(function(d){ if(!d) return; var main=d.querySelector('main'); if(!main) return;
  S.sections.forEach(function(k){ var el=d.querySelector('[data-section="'+k+'"]'); if(el) main.appendChild(el); }); }); }

// theme buttons
Array.prototype.forEach.call(document.querySelectorAll('#themes button'), function(b){
  b.classList.toggle('on', b.dataset.theme===S.theme);
  b.onclick=function(){ S.theme=b.dataset.theme;
    Array.prototype.forEach.call(document.querySelectorAll('#themes button'),function(x){x.classList.toggle('on',x===b);});
    applyTheme(S.theme); };
});

// scene dropdown (July)
var scene=document.getElementById('scene');
SCENES.forEach(function(s){ var o=document.createElement('option'); o.value=s;
  o.textContent=s.replace(/_/g,' ').replace(/\b\w/g,function(c){return c.toUpperCase();});
  scene.appendChild(o); });
scene.value = S.rotation['7'] || S.rotation[7] || 'silvermoon_city';
scene.onchange=function(){ S.rotation[7]=scene.value; };  // live scene needs a re-render (save)

// scrim slider
var scrim=document.getElementById('scrim'), scrimval=document.getElementById('scrimval');
scrim.value=S.scrim; scrimval.textContent=S.scrim+'%';
scrim.oninput=function(){ S.scrim=+scrim.value; scrimval.textContent=S.scrim+'%'; applyScrim(S.scrim); };

// section list with up/down + toggle
function renderSections(){
  var ul=document.getElementById('sections'); ul.innerHTML='';
  S.sections.forEach(function(k, i){
    var label=(SECTIONS.filter(function(p){return p[0]===k;})[0]||[k,k])[1];
    var off=S.hidden.indexOf(k)!==-1;
    var li=document.createElement('li'); if(off) li.className='off';
    li.innerHTML='<span class="grip">≡</span><span class="nm">'+label+'</span>'+
      '<button data-up>↑</button><button data-down>↓</button>'+
      '<button data-tog>'+(off?'▢':'☑')+'</button>';
    li.querySelector('[data-up]').onclick=function(){ if(i>0){ var a=S.sections; a.splice(i-1,0,a.splice(i,1)[0]); renderSections(); applyOrder(); } };
    li.querySelector('[data-down]').onclick=function(){ var a=S.sections; if(i<a.length-1){ a.splice(i+1,0,a.splice(i,1)[0]); renderSections(); applyOrder(); } };
    li.querySelector('[data-tog]').onclick=function(){ var h=S.hidden, x=h.indexOf(k); if(x===-1) h.push(k); else h.splice(x,1); renderSections(); applyHidden(); };
    ul.appendChild(li);
  });
}
renderSections();

// apply live state once the iframe loads
pv.addEventListener('load', function(){ applyTheme(S.theme); applyScrim(S.scrim); applyHidden(); applyOrder(); });

// save -> writes config + re-renders + reloads the preview
document.getElementById('save').onclick=function(){
  var btn=this, status=document.getElementById('status');
  btn.disabled=true; status.textContent='Saving & re-rendering…';
  fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(S)}).then(function(r){return r.json();}).then(function(res){
    btn.disabled=false;
    status.textContent = res.ok ? 'Saved. Preview updated.' : ('Error: '+(res.log||'').slice(-160));
    if(res.settings) S=Object.assign(S,res.settings);
    pv.src='/preview?'+Date.now();
  }).catch(function(e){ btn.disabled=false; status.textContent='Save failed: '+e; });
};
</script>
</body></html>
"""


if __name__ == "__main__":
    main()
