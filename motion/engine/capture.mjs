// Capture of one motion plan (motion.html#<spec.js>), in the renderer: the CODE CHECK first (zones of the phone on
// 10 frames, at most 3 texts, no overlap — window.check()), then, only if it is clean, the frames in N tabs (each
// frame depends on t alone), encoded to mp4. One JSON line on stdout: {ok, check, frames, seconds}.
//   node capture.mjs <file.html#spec.js> <out.mp4> <seconds> [fps=30] [tabs=3] [still.jpg]
import { createRequire } from 'module';
import { spawn, execFileSync } from 'child_process';
import fs from 'fs';
import path from 'path';
const require = createRequire('/app/package.json');
const WebSocket = require('ws');

const [, , page, out, secs = '5', fpsArg = '30', tabsArg = '1', still = ''] = process.argv;   // 1 tab: background tabs are not painted
const fps = Number(fpsArg), n = Math.round(Number(secs) * fps), tabs = Math.max(1, Math.min(4, Number(tabsArg)));
const t0 = Date.now();
const port = 9300 + Math.floor(Math.random() * 500);
const frames = fs.mkdtempSync('/tmp/motion_');
const chrome = spawn('chromium', ['--headless=new', '--no-sandbox', '--disable-gpu', '--hide-scrollbars',
  '--allow-file-access-from-files', `--remote-debugging-port=${port}`, '--window-size=1080,1920', 'about:blank'], { stdio: 'ignore' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const done = (o, code = 0) => { try { chrome.kill('SIGKILL'); } catch {} fs.rmSync(frames, { recursive: true, force: true });
  console.log(JSON.stringify({ ...o, seconds: (Date.now() - t0) / 1000 })); process.exit(code); };
try {
  let wsUrl;
  for (let k = 0; k < 60 && !wsUrl; k++) {
    try { wsUrl = (await (await fetch(`http://127.0.0.1:${port}/json/version`)).json()).webSocketDebuggerUrl; } catch { await sleep(250); } }
  const ws = new WebSocket(wsUrl); await new Promise(r => ws.on('open', r));
  let id = 0; const waiting = new Map();
  ws.on('message', m => { const d = JSON.parse(m); if (d.id && waiting.has(d.id)) { waiting.get(d.id)(d); waiting.delete(d.id); } });
  const send = (method, params = {}, sessionId) => new Promise(r => { const i = ++id; waiting.set(i, r);
    ws.send(JSON.stringify({ id: i, method, params, ...(sessionId ? { sessionId } : {}) })); });
  const open = async () => { const { result: { targetId } } = await send('Target.createTarget', { url: 'about:blank' });
    const { result: { sessionId } } = await send('Target.attachToTarget', { targetId, flatten: true });
    await send('Emulation.setDeviceMetricsOverride', { width: 1080, height: 1920, deviceScaleFactor: 1, mobile: false }, sessionId);
    await send('Page.enable', {}, sessionId); await send('Page.navigate', { url: 'file://' + page }, sessionId); return sessionId; };
  const S = await Promise.all([...Array(tabs)].map(open));
  await sleep(1500);
  const ev = async (expr, s = S[0]) => (await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true }, s)).result.result.value;
  const check = JSON.parse(await ev('JSON.stringify(window.check ? window.check() : ["pas de contrôle"])'));
  if (check.length) done({ ok: false, check }, 0);
  if (still) { await ev(`window.seek(${(Number(secs) * .8).toFixed(3)})`);
    const { result } = await send('Page.captureScreenshot', { format: 'jpeg', quality: 90 }, S[0]); fs.writeFileSync(still, Buffer.from(result.data, 'base64')); }
  await Promise.all(S.map(async (s, k) => { for (let f = k; f < n; f += tabs) {
    await send('Runtime.evaluate', { expression: `window.seek(${(f / fps).toFixed(4)})` }, s);
    const { result } = await send('Page.captureScreenshot', { format: 'jpeg', quality: 92 }, s);
    fs.writeFileSync(path.join(frames, String(f).padStart(4, '0') + '.jpg'), Buffer.from(result.data, 'base64')); } }));
  ws.close();
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-framerate', String(fps), '-i', path.join(frames, '%04d.jpg'),
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', out]);
  done({ ok: true, check: [], frames: n });
} catch (e) { done({ ok: false, error: String(e && e.message || e) }, 1); }
