#!/usr/bin/env python3
"""Soft-to-Rigid Packing: run a 3D experiment and open its replay in a browser.
Place this file in the repository root. Requires Python 3.10+ and Node.js.
"""
import argparse
import json
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from functools import partial

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / 'docs'
WORK = ROOT / '.packing_launcher'
DATA = DOCS / 'data' / 'packing_launcher_replay.json'
PAGE = DOCS / 'packing_launcher.html'
JS = WORK / 'run.js'

RUNNER = r'''"use strict";
const fs = require('node:fs');
const path = require('node:path');
const root = process.argv[2];
const output = process.argv[3];
const cfg = JSON.parse(process.argv[4]);
const P = require(path.join(root, 'src', 'cubes', 'sim3.js'));
const started = Date.now();
const r = P.run(cfg);
const replay = {n:r.cfg.n, record:r.side, frames:r.frames};
fs.writeFileSync(output + '.tmp', JSON.stringify(replay));
fs.renameSync(output + '.tmp', output);
console.log('n:', r.cfg.n, 'seed:', r.cfg.seed);
console.log('certified side:', r.side);
console.log('frames:', r.frames.length);
console.log('elapsed:', ((Date.now()-started)/1000).toFixed(2), 'seconds');
console.log('saved:', output);
'''

HTML = '''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Soft-to-Rigid Packing | Local Replay</title>
<link rel="stylesheet" href="assets/site.css">
<style>
body{padding:22px;background:#f3f6fb;color:#18263c;font-family:system-ui,sans-serif}
.wrap{max-width:1050px;margin:auto}h1{font-size:clamp(24px,4vw,38px)}
.viewer{background:white;border-radius:18px;padding:14px;overflow:hidden}
.stage{height:min(68vh,650px);min-height:340px;position:relative}
.stage canvas{display:block}.ctl{display:flex;gap:12px;padding:12px;align-items:center}
.ctl input{flex:1;min-width:0}.ctl button{padding:8px 16px;cursor:pointer}
.cap{padding:8px 14px;color:#4b5a70}.hud{pointer-events:none}
</style></head><body><div class="wrap">
<h1>Soft-to-Rigid Packing — Local 3D Replay</h1>
<p id="meta">Loading simulation data…</p>
<figure class="viewer" id="v3"><div class="stage"><div class="hud"></div></div>
<div class="ctl"><button type="button">Pause</button><input type="range" min="0" max="1000" value="0" aria-label="Replay timeline"></div>
<figcaption class="cap">Drag to rotate. Scroll to zoom. Play/Pause and timeline controls are below the viewer.</figcaption></figure>
<p>Source: <a href="https://github.com/yoheinakajima/soft-to-rigid-packing">yoheinakajima/soft-to-rigid-packing</a></p>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script src="assets/viewers.js"></script>
<script>
(async()=>{try{
const res=await fetch('data/packing_launcher_replay.json?ts='+Date.now());
if(!res.ok)throw Error('HTTP '+res.status);
const data=await res.json();
document.getElementById('meta').textContent=`${data.n} cubes · L = ${Number(data.record).toFixed(10)} · ${data.frames.length} frames`;
if(!window.SiteViewers||!window.THREE)throw Error('Viewer libraries could not be loaded (check internet connection).');
SiteViewers.cube(document.getElementById('v3'),data);
}catch(e){document.getElementById('meta').textContent='Replay error: '+e.message;console.error(e);}})();
</script></body></html>'''


def parse_args():
    p = argparse.ArgumentParser(description='Simulate 3D cube packing and open the browser replay.')
    p.add_argument('--n', type=int, default=8, help='Number of cubes (default: 8)')
    p.add_argument('--seed', type=int, default=17, help='Random seed (default: 17)')
    p.add_argument('--random-seed', action='store_true', help='Generate a fresh random 32-bit seed (default: off; overrides --seed)')
    p.add_argument('--compact', type=int, default=5000)
    p.add_argument('--morph', type=int, default=45000)
    p.add_argument('--settle', type=int, default=3000)
    p.add_argument('--rec-every', type=int, default=100, help='Save a frame every N steps')
    p.add_argument('--port', type=int, default=8000, help='Preferred localhost port; auto-fallback if occupied')
    p.add_argument('--no-browser', action='store_true', help='Do not open browser automatically')
    p.add_argument('--no-clean', action='store_true', help='Keep previous launcher files until overwritten')
    a = p.parse_args()
    if not 1 <= a.n <= 200: p.error('--n must be between 1 and 200')
    if not 0 <= a.seed <= 2**32-1: p.error('--seed must be 0..4294967295')
    for key in ('compact','morph','settle'):
        if getattr(a,key) < 1: p.error('--'+key+' must be positive')
    if a.rec_every < 1: p.error('--rec-every must be positive')
    if not 0 <= a.port <= 65535: p.error('--port must be 0..65535')
    return a


def main():
    a = parse_args()
    if not (ROOT/'src/cubes/sim3.js').is_file() or not (DOCS/'assets/viewers.js').is_file():
        sys.exit('ERROR: Put packing_launcher.py in the root of soft-to-rigid-packing-main (next to src/ and docs/).')
    if shutil.which('node') is None: sys.exit('ERROR: Node.js is missing from PATH. Install Node.js and reopen terminal.')
    if not a.no_clean:
        print('[1/4] Resetting launcher-generated files only (official files are untouched)...', flush=True)
        for path in (JS, DATA, DATA.with_suffix('.json.tmp'), PAGE):
            if path.exists(): path.unlink()
    else:
        print('[1/4] Keeping previous launcher files until replaced...', flush=True)
    WORK.mkdir(exist_ok=True)
    DATA.parent.mkdir(parents=True,exist_ok=True)
    JS.write_text(RUNNER,encoding='utf-8')
    seed = secrets.randbelow(2**32) if a.random_seed else a.seed
    config = dict(n=a.n,seed=seed,mode='improved',anneal=True,compact=a.compact,morph=a.morph,settle=a.settle,recEvery=a.rec_every)
    print(f'[2/4] Running n={a.n}, seed={seed}, steps={a.compact+a.morph+a.settle}...',flush=True)
    try:
        subprocess.run(['node',str(JS),str(ROOT),str(DATA),json.dumps(config)],cwd=ROOT,check=True)
    except subprocess.CalledProcessError as e:
        sys.exit(f'ERROR: Simulation failed (exit code {e.returncode}).')
    PAGE.write_text(HTML,encoding='utf-8')
    print('[3/4] Replay page generated.',flush=True)
    handler=partial(SimpleHTTPRequestHandler,directory=str(DOCS))
    try:
        server=ThreadingHTTPServer(('127.0.0.1',a.port),handler)
    except OSError:
        server=ThreadingHTTPServer(('127.0.0.1',0),handler)
        print(f'Port {a.port} was busy; using {server.server_port}.',flush=True)
    url=f'http://127.0.0.1:{server.server_port}/packing_launcher.html'
    print('[4/4] Viewer ready:',url,flush=True)
    print('Press Ctrl+C to stop the server. Run again with new arguments for a new simulation.',flush=True)
    if not a.no_browser:
        threading.Thread(target=lambda:(time.sleep(.5),webbrowser.open(url)),daemon=True).start()
    try: server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt: print('\nServer stopped.')
    finally: server.server_close()

if __name__=='__main__': main()
