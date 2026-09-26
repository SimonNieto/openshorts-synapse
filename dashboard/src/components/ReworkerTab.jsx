import React, { useState, useRef, useCallback, useEffect } from 'react';
import { Loader2, Upload, Eraser, RotateCcw, AlertCircle, X, Play, Pause, ScanText, Eye } from 'lucide-react';
import { apiFetch, apiJson } from '../lib/api';
import { getApiUrl } from '../config';
import { LANGUAGES } from './TranslateModal';

// Fresh state: one box starts drawn as a reasonable guess (a caption bar
// across the top third, where a hook usually sits, for the first 5s — the
// usual hook duration) so there's something to see and drag-adjust
// immediately. Draw more (e.g. over the old captions, later in the clip) by
// scrubbing the video to that moment and dragging elsewhere on the frame —
// every drag adds a box, it doesn't replace the last one.
const DEFAULT_BOXES = [{ x: 0.08, y: 0.04, w: 0.84, h: 0.14, start: 0, end: 5 }];

// Empty start/end (cleared by hand) means "the whole clip" server-side.
const cleanBoxes = (boxes) => boxes.map((b) => ({
  x: b.x, y: b.y, w: b.w, h: b.h,
  start: b.start === '' || b.start == null ? null : Number(b.start),
  end: b.end === '' || b.end == null ? null : Number(b.end),
}));

const fmtTime = (s) => {
  const n = Math.max(0, Number(s) || 0);
  const m = Math.floor(n / 60);
  const r = (n % 60).toFixed(1);
  return `${m}:${r.padStart(4, '0')}`;
};

// So a page reload (or the dev server hot-reloading mid-job) doesn't strand
// a still-processing clip with no way back to it. Mirrors the main app's
// session-recovery localStorage pattern (App.jsx SESSION_KEY).
const REWORK_SESSION_KEY = 'openshorts_rework_session';

// onDone(jobId): called once erasing finishes. The pipeline stops there — no
// hook or captions burned — and instead registers the result as a normal
// completed job, so the caller can hand off straight into the Clip
// Generator's own results view (ResultCard: edit clip, reframing, subtitles,
// viral hook, dub voice) instead of a second, thinner set of controls here.
export default function ReworkerTab({ geminiApiKey, elevenLabsKey, onDone }) {
  const [stage, setStage] = useState('upload'); // upload | configure | processing | error
  const [error, setError] = useState('');
  const [jobId, setJobId] = useState(null);
  const [source, setSource] = useState(null); // { url, width, height, duration }
  const [boxes, setBoxes] = useState(DEFAULT_BOXES);
  const [targetLanguage, setTargetLanguage] = useState(''); // dub: replaces the voice
  const [flip, setFlip] = useState(false);
  const [speed, setSpeed] = useState(1.0);
  const [zoom, setZoom] = useState(1.0);
  const [colorBoost, setColorBoost] = useState(1.0);
  const [logs, setLogs] = useState([]);
  const [progress, setProgress] = useState(0);
  const [draft, setDraft] = useState(null); // box being drawn right now, not yet committed
  const [currentTime, setCurrentTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  // smart: only the letters are erased, the background behind them is
  // carried in from neighbouring frames. legacy: the old whole-box blur.
  const [eraseMode, setEraseMode] = useState('smart');
  const [detecting, setDetecting] = useState(false);
  const [detectNote, setDetectNote] = useState('');
  const [preview, setPreview] = useState(null); // {status, url?, error?}
  const dragStart = useRef(null); // fraction {x,y} where the current drag began
  const frameRef = useRef(null);
  const videoRef = useRef(null);
  const fileInputRef = useRef(null);
  const pollTimer = useRef(null);
  const previewTimer = useRef(null);

  useEffect(() => () => { clearTimeout(pollTimer.current); clearTimeout(previewTimer.current); }, []);

  const reset = () => {
    setStage('upload'); setError(''); setJobId(null); setSource(null);
    setBoxes(DEFAULT_BOXES); setTargetLanguage('');
    setFlip(false); setSpeed(1.0); setZoom(1.0); setColorBoost(1.0);
    setLogs([]); setProgress(0); setDraft(null); dragStart.current = null;
    setDetectNote(''); setPreview(null); clearTimeout(previewTimer.current);
  };

  // Finds the old captions / hook on its own (no AI call, a few seconds) and
  // pre-draws them; everything stays editable by hand.
  const runDetect = async (id, duration) => {
    setDetecting(true);
    setDetectNote('');
    try {
      const data = await apiJson(`/api/rework/detect/${id}`);
      const found = (data.boxes || []).map((b) => ({
        x: b.x, y: b.y, w: b.w, h: b.h, kind: b.kind,
        start: b.kind === 'captions' ? 0 : b.start,
        end: b.kind === 'captions' ? Math.floor((duration || b.end || 0) * 10) / 10 : b.end,
      }));
      if (found.length) {
        setBoxes(found);
        setDetectNote(`${found.length} text region${found.length === 1 ? '' : 's'} found automatically — check them, adjust or draw more.`);
      } else {
        setDetectNote('No burned-in text found automatically — draw the boxes by hand.');
      }
    } catch (_) {
      setDetectNote('Automatic detection failed — draw the boxes by hand.');
    } finally {
      setDetecting(false);
    }
  };

  const pollPreview = async (id) => {
    try {
      const data = await apiJson(`/api/rework/preview/${id}`);
      if (data.status === 'running') {
        previewTimer.current = setTimeout(() => pollPreview(id), 2000);
        return;
      }
      setPreview(data.status === 'done' ? { status: 'done', url: getApiUrl(data.url) }
        : { status: 'failed', error: data.error || 'Preview failed' });
    } catch (_) {
      previewTimer.current = setTimeout(() => pollPreview(id), 4000);
    }
  };

  // Erases 3 s around the current time exactly like the real run, so the
  // result can be judged before spending minutes on the whole clip.
  const startPreview = async () => {
    if (!boxes.length) { setError('Draw at least one region first.'); return; }
    setError('');
    setPreview({ status: 'running' });
    try {
      const res = await apiFetch('/api/rework/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: jobId, boxes: cleanBoxes(boxes), at: currentTime, erase_mode: eraseMode,
        }),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => '');
        let detail = text;
        try { detail = JSON.parse(text).detail || text; } catch (_) { /* keep raw */ }
        throw new Error(detail || 'Preview failed');
      }
      pollPreview(jobId);
    } catch (e) {
      setPreview({ status: 'failed', error: e.message });
    }
  };

  const handleFile = async (file) => {
    if (!file) return;
    setError('');
    setStage('uploading');
    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await apiFetch('/api/rework/upload', { method: 'POST', body: formData });
      if (!res.ok) {
        const text = await res.text().catch(() => '');
        throw new Error(text || 'Upload failed');
      }
      const data = await res.json();
      setJobId(data.job_id);
      setSource({
        url: getApiUrl(data.source_url), width: data.width, height: data.height,
        duration: data.duration,
      });
      setBoxes(DEFAULT_BOXES);
      setPreview(null);
      setStage('configure');
      runDetect(data.job_id, data.duration);
    } catch (e) {
      setError(e.message || 'Upload failed');
      setStage('upload');
    }
  };

  // --- drag-to-draw erase boxes over the preview frame ----------------------
  // Every drag adds a new box (hook, captions, a watermark — draw as many as
  // there are things to erase); it never replaces an existing one.
  const fractionsFromEvent = useCallback((e) => {
    const el = frameRef.current;
    if (!el) return { x: 0, y: 0 };
    const rect = el.getBoundingClientRect();
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const clientY = e.touches ? e.touches[0].clientY : e.clientY;
    return {
      x: Math.min(1, Math.max(0, (clientX - rect.left) / rect.width)),
      y: Math.min(1, Math.max(0, (clientY - rect.top) / rect.height)),
    };
  }, []);

  const startDrag = (e) => {
    e.preventDefault();
    const p = fractionsFromEvent(e);
    dragStart.current = p;
    setDraft({ x: p.x, y: p.y, w: 0, h: 0 });
  };

  useEffect(() => {
    const move = (e) => {
      if (!dragStart.current) return;
      const p = fractionsFromEvent(e);
      const start = dragStart.current;
      setDraft({
        x: Math.min(start.x, p.x),
        y: Math.min(start.y, p.y),
        w: Math.abs(p.x - start.x),
        h: Math.abs(p.y - start.y),
      });
    };
    const stop = () => {
      if (!dragStart.current) return;
      dragStart.current = null;
      setDraft((d) => {
        if (d && d.w > 0.02 && d.h > 0.02) {
          // Defaults the new region's time range to a 5s window starting at
          // wherever the video was scrubbed to — the whole point of being
          // able to seek before drawing is to land the range on the right
          // moment without typing it in by hand first.
          const duration = source?.duration || 0;
          const t = videoRef.current?.currentTime || 0;
          const start = Math.round(t * 10) / 10;
          const end = Math.round(Math.min(duration, t + 5) * 10) / 10;
          setBoxes((prev) => [...prev, { ...d, start, end }]);
        }
        return null;
      });
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', stop);
    window.addEventListener('touchmove', move);
    window.addEventListener('touchend', stop);
    return () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', stop);
      window.removeEventListener('touchmove', move);
      window.removeEventListener('touchend', stop);
    };
  }, [fractionsFromEvent, source]);

  const removeBox = (index) => setBoxes((prev) => prev.filter((_, i) => i !== index));

  const updateBoxTime = (index, field, value) => {
    const n = value === '' ? '' : Math.max(0, Number(value));
    setBoxes((prev) => prev.map((b, i) => (i === index ? { ...b, [field]: n } : b)));
  };

  const seekTo = (t) => {
    if (videoRef.current) videoRef.current.currentTime = t;
    setCurrentTime(t);
  };

  const togglePlay = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) v.play(); else v.pause();
  };

  // --- submit + poll ---------------------------------------------------------
  const poll = async (id) => {
    try {
      const data = await apiJson(`/api/rework/status/${id}`);
      setLogs(data.logs || []);
      setProgress(data.progress || 0);
      if (data.status === 'completed') {
        localStorage.removeItem(REWORK_SESSION_KEY);
        await onDone(data.result?.job_id || id);
        return;
      }
      if (data.status === 'failed') {
        setError((data.logs || []).slice(-1)[0] || 'Processing failed');
        setStage('error');
        return;
      }
      pollTimer.current = setTimeout(() => poll(id), 2500);
    } catch (e) {
      // A 404 means the server no longer knows this job at all (e.g. it was
      // restarted mid-processing — the tracker is in-memory, nothing to
      // resume from). Retrying forever would just spin silently; say so.
      if (e.status === 404) {
        setError('Lost track of this job (the server may have restarted while it was processing). Please try again.');
        setStage('error');
        return;
      }
      pollTimer.current = setTimeout(() => poll(id), 4000);
    }
  };

  // Restore an in-flight job after a reload, so neither a page refresh nor
  // the dev server hot-reloading strands it with no way back (see
  // REWORK_SESSION_KEY above). A finished job hands off to the dashboard
  // immediately, so there's nothing of "done" left to restore.
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(REWORK_SESSION_KEY) || 'null');
      if (!saved?.jobId) return;
      // An older session (e.g. saved before a field was renamed) can carry a
      // stage with none of the state it needs to render — 'configure' with
      // no source is a blank screen, not an upload prompt, since neither
      // block's condition is met. Only restore a stage whose required data
      // actually came along with it; anything else falls back to 'upload'
      // (the safe default already in place) instead of a dead end.
      if (saved.stage === 'configure' && saved.source) {
        setJobId(saved.jobId);
        setSource(saved.source);
        if (saved.boxes) setBoxes(saved.boxes);
        if (saved.targetLanguage) setTargetLanguage(saved.targetLanguage);
        if (saved.flip) setFlip(saved.flip);
        if (saved.speed) setSpeed(saved.speed);
        if (saved.zoom) setZoom(saved.zoom);
        if (saved.colorBoost) setColorBoost(saved.colorBoost);
        if (saved.eraseMode) setEraseMode(saved.eraseMode);
        setStage('configure');
      } else if (saved.stage === 'processing') {
        setJobId(saved.jobId);
        setStage('processing');
        setLogs(['Resuming after reload...']);
        poll(saved.jobId);
      } else {
        localStorage.removeItem(REWORK_SESSION_KEY);
      }
    } catch (_) { /* corrupt/old entry — ignore, start fresh */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Persist just enough to restore the screen above, every time it changes.
  useEffect(() => {
    if (stage === 'upload' || stage === 'uploading') {
      localStorage.removeItem(REWORK_SESSION_KEY);
      return;
    }
    try {
      localStorage.setItem(REWORK_SESSION_KEY, JSON.stringify({
        jobId, source, boxes, targetLanguage,
        flip, speed, zoom, colorBoost, eraseMode, stage,
      }));
    } catch (_) { /* storage full/unavailable — the reload-recovery is best-effort */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, stage]);

  const handleSubmit = async () => {
    if (!geminiApiKey) { setError('Set your Gemini API key in Settings first.'); return; }
    if (targetLanguage && !elevenLabsKey) { setError('Set your ElevenLabs API key in Settings to translate.'); return; }
    if (boxes.length === 0) { setError('Drag a box over the old hook (and captions, if any) first.'); return; }
    if (boxes.some((b) => b.start !== '' && b.end !== '' && Number(b.start) >= Number(b.end))) {
      setError('Each region\'s start time must be before its end time.');
      return;
    }

    setError('');
    setStage('processing');
    setLogs(['Starting...']);
    try {
      const headers = { 'Content-Type': 'application/json', 'X-Gemini-Key': geminiApiKey };
      if (targetLanguage) headers['X-ElevenLabs-Key'] = elevenLabsKey;
      const res = await apiFetch('/api/rework/process', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          job_id: jobId, boxes: cleanBoxes(boxes),
          target_language: targetLanguage || null,
          variations: { flip, speed, zoom, color_boost: colorBoost },
          erase_mode: eraseMode,
        }),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => '');
        let detail = text;
        try { detail = JSON.parse(text).detail || text; } catch (_) { /* keep raw */ }
        throw new Error(typeof detail === 'string' ? detail : text);
      }
      poll(jobId);
    } catch (e) {
      setError(e.message || 'Could not start processing');
      setStage('configure');
    }
  };

  return (
    <div className="h-full overflow-y-auto p-8 max-w-3xl mx-auto animate-fade">
      <p className="eyebrow mb-1.5">08 · REWORKER</p>
      <h1 className="font-display lowercase text-2xl text-ink mb-2">viral clip reworker</h1>
      <p className="text-muted text-sm mb-8 lowercase">
        Upload a clip and erase its existing hook and captions — with an optional dub. Once erased, the clip
        opens in the Clip Generator's own editor, with the same hook / subtitle / reframing tools as any
        generated clip. The old text is found automatically; only the letters are erased, and what was behind
        them is rebuilt from the neighbouring frames. Text parked for seconds on a moving face can still leave
        a soft patch — use the preview to judge before running the whole clip.
      </p>

      {error && (
        <div className="mb-5 flex items-start gap-2 text-danger text-sm">
          <AlertCircle size={16} className="shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* stage === 'configure' with no source is an impossible-but-seen combo
          (a stale localStorage entry from before a field rename): fall back
          to the upload prompt rather than rendering nothing. */}
      {(stage === 'upload' || (stage === 'configure' && !source)) && (
        <div
          className="card border-dashed border-2 border-rule rounded-card p-12 text-center cursor-pointer hover:border-brass transition-colors"
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault(); handleFile(e.dataTransfer.files?.[0]); }}
        >
          <Upload size={32} className="mx-auto mb-3 text-muted" />
          <p className="text-sm text-ink lowercase">click to upload or drag and drop</p>
          <p className="readout mt-1">MP4, MOV</p>
          <input
            ref={fileInputRef}
            type="file"
            accept="video/*"
            className="hidden"
            onChange={(e) => handleFile(e.target.files?.[0])}
          />
        </div>
      )}

      {stage === 'uploading' && (
        <div className="flex flex-col items-center justify-center py-20 gap-3">
          <Loader2 size={28} className="animate-spin text-brass" />
          <p className="text-sm text-muted lowercase">uploading...</p>
        </div>
      )}

      {stage === 'configure' && source && (
        <div className="space-y-6">
          <div>
            <label className="eyebrow block mb-2">
              scrub to the moment, then drag a box over the old hook — and again over the old captions, if any
            </label>
            <p className="text-xs text-muted mb-2">
              Old captions usually run through the whole clip, not just a few seconds — use "whole clip" below
              on that region, or your new captions will overlap whatever's left unerased after your end time.
            </p>
            <div className="flex items-center gap-3 mb-3">
              <button
                onClick={() => runDetect(jobId, source.duration)}
                disabled={detecting}
                className="btn-ghost text-xs flex items-center gap-1.5 shrink-0"
                title="find the old captions and hook automatically (replaces the current boxes)"
              >
                {detecting ? <Loader2 size={12} className="animate-spin" /> : <ScanText size={12} />}
                {detecting ? 'detecting text...' : 'auto-detect text'}
              </button>
              {detectNote && <span className="text-xs text-muted">{detectNote}</span>}
            </div>
            <div
              ref={frameRef}
              className="relative select-none rounded-card overflow-hidden bg-black mx-auto"
              style={{ aspectRatio: `${source.width} / ${source.height}`, maxWidth: 320 }}
              onMouseDown={startDrag}
              onTouchStart={startDrag}
            >
              <video
                ref={videoRef}
                src={source.url}
                className="w-full h-full object-contain pointer-events-none"
                playsInline
                onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
                onPlay={() => setPlaying(true)}
                onPause={() => setPlaying(false)}
              />
              {boxes.map((b, i) => {
                const active = (b.start == null || currentTime >= b.start) && (b.end == null || currentTime <= b.end);
                return (
                  <div
                    key={i}
                    className={`absolute border-2 bg-brass/20 group transition-opacity ${active ? 'border-brass opacity-100' : 'border-brass/40 opacity-40'}`}
                    style={{ left: `${b.x * 100}%`, top: `${b.y * 100}%`, width: `${b.w * 100}%`, height: `${b.h * 100}%` }}
                  >
                    <button
                      onClick={(e) => { e.stopPropagation(); removeBox(i); }}
                      onMouseDown={(e) => e.stopPropagation()}
                      className="absolute -top-2 -right-2 w-4 h-4 rounded-full bg-danger text-white flex items-center justify-center opacity-70 group-hover:opacity-100"
                      title="remove this region"
                    >
                      <X size={10} />
                    </button>
                  </div>
                );
              })}
              {draft && draft.w > 0 && draft.h > 0 && (
                <div
                  className="absolute border-2 border-dashed border-brass bg-brass/10 pointer-events-none"
                  style={{ left: `${draft.x * 100}%`, top: `${draft.y * 100}%`, width: `${draft.w * 100}%`, height: `${draft.h * 100}%` }}
                />
              )}
            </div>

            {/* Custom transport, not native <video controls>: those would sit
                under our drag overlay and be unreachable, since the overlay
                has to cover the whole frame to map drag coordinates correctly. */}
            <div className="flex items-center gap-2 mt-2 mx-auto" style={{ maxWidth: 320 }}>
              <button onClick={togglePlay} className="btn-ghost p-1.5 shrink-0" title={playing ? 'pause' : 'play'}>
                {playing ? <Pause size={14} /> : <Play size={14} />}
              </button>
              <input
                type="range"
                min={0}
                max={source.duration || 0}
                step={0.05}
                value={currentTime}
                onChange={(e) => seekTo(Number(e.target.value))}
                className="flex-1"
              />
              <span className="readout shrink-0 w-20 text-right">{fmtTime(currentTime)} / {fmtTime(source.duration)}</span>
            </div>

            <div className="flex items-center justify-between mt-3">
              <span className="readout">{boxes.length} region{boxes.length === 1 ? '' : 's'} to erase</span>
              <button onClick={() => setBoxes(DEFAULT_BOXES)} className="btn-ghost text-xs flex items-center gap-1">
                <RotateCcw size={12} /> reset
              </button>
            </div>

            {boxes.length > 0 && (
              <div className="space-y-2 mt-2">
                {boxes.map((b, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    <span className="readout w-16 shrink-0" title={b.kind ? `found automatically: ${b.kind}` : undefined}>
                      {b.kind || `region ${i + 1}`}
                    </span>
                    <input
                      type="number" min={0} step={0.1} value={b.start ?? ''}
                      onChange={(e) => updateBoxTime(i, 'start', e.target.value)}
                      className="input-field w-16 py-1 px-2 text-xs"
                    />
                    <button
                      onClick={() => seekTo(Number(b.start) || 0)}
                      className="text-brass hover:underline shrink-0"
                      title="seek video to this region's start"
                    >
                      <Play size={11} />
                    </button>
                    <span className="text-muted">to</span>
                    <input
                      type="number" min={0} step={0.1} value={b.end ?? ''}
                      onChange={(e) => updateBoxTime(i, 'end', e.target.value)}
                      className="input-field w-16 py-1 px-2 text-xs"
                    />
                    <span className="readout">sec</span>
                    <button
                      onClick={() => setBoxes((prev) => prev.map((box, j) => (j === i ? { ...box, start: 0, end: Math.floor((source.duration || 0) * 10) / 10 } : box)))}
                      className="btn-ghost text-[11px] px-2 py-0.5 ml-auto shrink-0"
                      title="repeats through the whole clip (e.g. a caption bar, not a one-off hook)"
                    >
                      whole clip
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div>
            <label className="eyebrow block mb-2">erase quality</label>
            <select value={eraseMode} onChange={(e) => { setEraseMode(e.target.value); setPreview(null); }} className="input-field appearance-none cursor-pointer">
              <option value="smart">smart — letters only, background rebuilt from other frames (recommended)</option>
              <option value="legacy">fast — blur the whole box (old method, visible smear)</option>
            </select>
            <div className="flex items-center gap-3 mt-3">
              <button
                onClick={startPreview}
                disabled={preview?.status === 'running' || boxes.length === 0}
                className="btn-ghost text-xs flex items-center gap-1.5 shrink-0"
                title="erase 3 seconds around the current video time and show before / after"
              >
                {preview?.status === 'running' ? <Loader2 size={12} className="animate-spin" /> : <Eye size={12} />}
                {preview?.status === 'running' ? 'rendering preview (~30 s)...' : `preview 3 s around ${fmtTime(currentTime)}`}
              </button>
              {preview?.status === 'failed' && <span className="text-xs text-danger">{preview.error}</span>}
            </div>
            {preview?.status === 'done' && (
              <div className="mt-3">
                <div className="flex justify-around readout mb-1 mx-auto" style={{ maxWidth: 480 }}>
                  <span>before</span><span>after</span>
                </div>
                <video
                  key={preview.url}
                  src={preview.url}
                  className="w-full rounded-card bg-black mx-auto block"
                  style={{ maxWidth: 480 }}
                  autoPlay loop muted playsInline controls
                />
              </div>
            )}
          </div>

          <div>
            <label className="eyebrow block mb-2">dub voice</label>
            <select value={targetLanguage} onChange={(e) => setTargetLanguage(e.target.value)} className="input-field appearance-none cursor-pointer">
              <option value="">original (no dub)</option>
              {Object.entries(LANGUAGES).sort((a, b) => a[1].localeCompare(b[1])).map(([code, name]) => (
                <option key={code} value={code}>{name}</option>
              ))}
            </select>
            <p className="text-xs text-muted mt-1">
              replaces the voice with an AI dub. Want captions in a different language instead (voice unchanged)?
              Do that afterwards from the subtitles tool's own "translate captions" — works on any clip.
            </p>
          </div>

          {/* Small, deliberately-imperfect variations: a platform's
              duplicate/recycled-content check is frame-hash-based, not
              semantic, so a flip/speed/zoom/color nudge changes the file's
              fingerprint without being visible to a viewer. */}
          <div>
            <label className="eyebrow block mb-2">vary the edit (optional)</label>
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm text-ink lowercase">flip horizontally</span>
              <label className="relative inline-flex items-center cursor-pointer">
                <input type="checkbox" checked={flip} onChange={(e) => setFlip(e.target.checked)} className="sr-only peer" />
                <div className="w-8 h-4 rounded-full bg-paper3 peer-checked:bg-brass transition-colors after:content-[''] after:absolute after:top-0 after:left-0 after:h-4 after:w-4 after:rounded-full after:bg-ink after:transition-all peer-checked:after:translate-x-full" />
              </label>
            </div>
            <div className="grid grid-cols-3 gap-4">
              <div>
                <div className="flex justify-between mb-1"><span className="readout">speed</span><span className="readout">{Math.round(speed * 100)}%</span></div>
                <input type="range" min="0.95" max="1.05" step="0.01" value={speed} onChange={(e) => setSpeed(Number(e.target.value))} className="w-full accent-brass" />
              </div>
              <div>
                <div className="flex justify-between mb-1"><span className="readout">zoom</span><span className="readout">{Math.round(zoom * 100)}%</span></div>
                <input type="range" min="1.0" max="1.15" step="0.01" value={zoom} onChange={(e) => setZoom(Number(e.target.value))} className="w-full accent-brass" />
              </div>
              <div>
                <div className="flex justify-between mb-1"><span className="readout">color</span><span className="readout">{Math.round(colorBoost * 100)}%</span></div>
                <input type="range" min="1.0" max="1.2" step="0.01" value={colorBoost} onChange={(e) => setColorBoost(Number(e.target.value))} className="w-full accent-brass" />
              </div>
            </div>
          </div>

          <div className="flex gap-3">
            <button onClick={reset} className="btn-ghost flex-1">cancel</button>
            <button onClick={handleSubmit} className="btn-primary flex-1 flex items-center justify-center gap-2">
              <Eraser size={16} /> erase and open in editor
            </button>
          </div>
        </div>
      )}

      {stage === 'processing' && (
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <Loader2 size={20} className="animate-spin text-brass" />
            <p className="text-sm text-ink lowercase">erasing — this can take a minute</p>
            <span className="readout ml-auto">{progress}%</span>
          </div>
          <div className="h-1.5 rounded-full bg-paper3 overflow-hidden">
            <div className="h-full bg-brass transition-all duration-500" style={{ width: `${progress}%` }} />
          </div>
          <div className="card p-4 max-h-64 overflow-y-auto font-mono text-xs text-muted space-y-1">
            {logs.map((l, i) => <div key={i}>{l}</div>)}
          </div>
        </div>
      )}

      {stage === 'error' && (
        <div className="text-center py-10">
          <button onClick={reset} className="btn-primary">try again</button>
        </div>
      )}
    </div>
  );
}
