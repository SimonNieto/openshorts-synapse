import React, { useState, useRef, useCallback, useEffect } from 'react';
import { Loader2, Upload, Eraser, RotateCcw, AlertCircle, X, Play, Pause, ScanText, Eye } from 'lucide-react';
import { apiFetch, apiJson } from '../lib/api';
import { getApiUrl } from '../config';
import { LANGUAGES } from './TranslateModal';
import StepIndicator from './ui/StepIndicator';
import SegmentedControl from './ui/SegmentedControl';

// The three parts of the flow, for the stepper (presentation only).
const FLOW_STEPS = ['Source', 'Options', 'Result'];

// Small icon buttons grow to the 44px touch floor on coarse pointers (design.md).
const TOUCH_TARGET = '[@media(pointer:coarse)]:min-w-[44px] [@media(pointer:coarse)]:min-h-[44px]';

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

  // --- Presentation only (derived from the state above) ---------------------
  const flowStep = (stage === 'processing' || stage === 'error') ? 2 : (stage === 'configure' && source) ? 1 : 0;
  // Validation errors raised while configuring show next to the action that raised them.
  const errorNearActions = stage === 'configure' && !!source;
  const errorBox = error ? (
    <div role="alert" className="flex items-start gap-2.5 rounded-input border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-ink">
      <AlertCircle size={16} className="text-danger shrink-0 mt-0.5" aria-hidden="true" />
      <span className="break-words">{error}</span>
    </div>
  ) : null;
  const previewRunning = preview?.status === 'running';

  return (
    <div className="max-w-5xl mx-auto p-4 sm:p-8 space-y-8 animate-fade">
      <header className="max-w-3xl">
        <p className="eyebrow mb-2">Rework</p>
        <h2 className="page-title">Wipe a viral clip clean</h2>
        <p className="page-lede mt-3">
          Upload a clip and erase its burned-in hook and captions, with an optional dub. Once erased, the clip opens
          in the Clip Generator's own editor, with the same hook, subtitle and reframing tools as any generated clip.
        </p>
      </header>

      <div className="border-y border-rule py-4">
        <StepIndicator steps={FLOW_STEPS} current={flowStep} />
      </div>

      {!errorNearActions && errorBox}

      {/* ===== 1 · Source ===== */}
      {/* stage === 'configure' with no source is an impossible-but-seen combo
          (a stale localStorage entry from before a field rename): fall back
          to the upload prompt rather than rendering nothing. */}
      {(stage === 'upload' || (stage === 'configure' && !source)) && (
        <section aria-labelledby="rw-source-heading" className="space-y-4">
          <h3 id="rw-source-heading" className="font-display text-xl text-ink">Source clip</h3>
          <button
            type="button"
            className="card-print card-hover w-full border-dashed px-6 py-12 sm:py-16 text-center"
            onClick={() => fileInputRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); handleFile(e.dataTransfer.files?.[0]); }}
          >
            <span className="mx-auto mb-4 w-14 h-14 rounded-card border border-rule2 bg-paper3 flex items-center justify-center" aria-hidden="true">
              <Upload size={22} className="text-ink" />
            </span>
            <span className="block font-display text-lg text-ink">Choose a clip or drop it here</span>
            <span className="block text-sm text-muted mt-1.5">The one whose hook and captions you want gone.</span>
            <span className="readout block mt-3">MP4 · MOV</span>
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="video/*"
            className="hidden"
            onChange={(e) => handleFile(e.target.files?.[0])}
          />
        </section>
      )}

      {stage === 'uploading' && (
        <section aria-labelledby="rw-uploading-heading" className="card flex flex-col items-center justify-center gap-3 py-16 text-center" role="status">
          <Loader2 size={28} className="animate-spin text-muted" aria-hidden="true" />
          <h3 id="rw-uploading-heading" className="text-sm font-medium text-ink2">Uploading the clip…</h3>
        </section>
      )}

      {/* ===== 2 · Options ===== */}
      {stage === 'configure' && source && (
        <div className="space-y-8">
          <div className="grid lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] gap-8 items-start">
            {/* Regions to erase */}
            <section aria-labelledby="rw-regions-heading" className="space-y-4 min-w-0">
              <div>
                <h3 id="rw-regions-heading" className="font-display text-xl text-ink">Mark the old text</h3>
                <p className="text-sm text-ink2 mt-1.5">
                  Scrub to the moment, then drag a box over the old hook, and again over the old captions if any.
                </p>
              </div>

              <div className="space-y-2">
                <button
                  type="button"
                  onClick={() => runDetect(jobId, source.duration)}
                  disabled={detecting}
                  className="btn-ghost"
                  title="Find the old captions and hook automatically (replaces the current boxes)"
                >
                  {detecting ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <ScanText size={14} aria-hidden="true" />}
                  {detecting ? 'Detecting text…' : 'Auto-detect text'}
                </button>
                <p className="text-sm text-muted" aria-live="polite">{detectNote}</p>
              </div>

              <div
                ref={frameRef}
                role="group"
                aria-label="Clip frame: drag to draw a region to erase"
                className="relative select-none touch-none cursor-crosshair rounded-input overflow-hidden bg-black border border-rule2 mx-auto"
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
                      className={`absolute border-2 border-ink bg-paper/35 group transition-opacity ${active ? 'opacity-100' : 'opacity-40'}`}
                      style={{ left: `${b.x * 100}%`, top: `${b.y * 100}%`, width: `${b.w * 100}%`, height: `${b.h * 100}%` }}
                    >
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); removeBox(i); }}
                        onMouseDown={(e) => e.stopPropagation()}
                        className="absolute -top-2.5 -right-2.5 w-6 h-6 rounded-full bg-paper2 text-ink border border-rule2 flex items-center justify-center opacity-80 group-hover:opacity-100 focus-visible:opacity-100"
                        title="Remove this region"
                        aria-label={`Remove region ${i + 1}`}
                      >
                        <X size={12} aria-hidden="true" />
                      </button>
                    </div>
                  );
                })}
                {draft && draft.w > 0 && draft.h > 0 && (
                  <div
                    className="absolute border-2 border-dashed border-ink bg-paper/20 pointer-events-none"
                    style={{ left: `${draft.x * 100}%`, top: `${draft.y * 100}%`, width: `${draft.w * 100}%`, height: `${draft.h * 100}%` }}
                  />
                )}
              </div>

              {/* Custom transport, not native <video controls>: those would sit
                  under our drag overlay and be unreachable, since the overlay
                  has to cover the whole frame to map drag coordinates correctly. */}
              <div className="flex items-center gap-2 mx-auto" style={{ maxWidth: 320 }}>
                <button
                  type="button"
                  onClick={togglePlay}
                  className={`btn-ghost p-2 shrink-0 ${TOUCH_TARGET}`}
                  aria-label={playing ? 'Pause' : 'Play'}
                >
                  {playing ? <Pause size={16} aria-hidden="true" /> : <Play size={16} aria-hidden="true" />}
                </button>
                <label htmlFor="rw-seek" className="sr-only">Clip position</label>
                <input
                  id="rw-seek"
                  type="range"
                  min={0}
                  max={source.duration || 0}
                  step={0.05}
                  value={currentTime}
                  onChange={(e) => seekTo(Number(e.target.value))}
                  className="flex-1 min-w-0 accent-ink"
                />
                <span className="readout shrink-0">{fmtTime(currentTime)} / {fmtTime(source.duration)}</span>
              </div>

              <div className="flex items-center justify-between gap-3 pt-2 border-t border-rule">
                <p className="readout">{boxes.length} region{boxes.length === 1 ? '' : 's'} to erase</p>
                <button type="button" onClick={() => setBoxes(DEFAULT_BOXES)} className="btn-quiet">
                  <RotateCcw size={14} aria-hidden="true" /> Reset
                </button>
              </div>
              <p className="text-xs text-muted">
                Old captions usually run through the whole clip, not just a few seconds. Use “Whole clip” on that
                region, or your new captions will overlap whatever is left unerased after the end time.
              </p>

              {boxes.length > 0 && (
                <ol className="space-y-2">
                  {boxes.map((b, i) => (
                    <li key={i} className="tray p-3 space-y-2.5">
                      <div className="flex items-center gap-2">
                        <span className="readout flex-1 min-w-0 truncate" title={b.kind ? `Found automatically: ${b.kind}` : undefined}>
                          {b.kind || `Region ${i + 1}`}
                        </span>
                        <button
                          type="button"
                          onClick={() => setBoxes((prev) => prev.map((box, j) => (j === i ? { ...box, start: 0, end: Math.floor((source.duration || 0) * 10) / 10 } : box)))}
                          className="btn-ghost px-2.5 py-1 text-xs shrink-0"
                          title="Repeats through the whole clip (e.g. a caption bar, not a one-off hook)"
                        >
                          Whole clip
                        </button>
                        <button
                          type="button"
                          onClick={() => removeBox(i)}
                          className={`btn-danger p-2 shrink-0 ${TOUCH_TARGET}`}
                          aria-label={`Remove region ${i + 1}`}
                        >
                          <X size={14} aria-hidden="true" />
                        </button>
                      </div>
                      <div className="flex flex-wrap items-center gap-2 text-sm">
                        <label htmlFor={`rw-start-${i}`} className="sr-only">Region {i + 1} start, in seconds</label>
                        <input
                          id={`rw-start-${i}`}
                          type="number" min={0} step={0.1} value={b.start ?? ''}
                          onChange={(e) => updateBoxTime(i, 'start', e.target.value)}
                          className="input-field w-20 py-1.5 px-2"
                        />
                        <button
                          type="button"
                          onClick={() => seekTo(Number(b.start) || 0)}
                          className={`btn-quiet p-2 shrink-0 ${TOUCH_TARGET}`}
                          title="Seek video to this region's start"
                          aria-label={`Jump to the start of region ${i + 1}`}
                        >
                          <Play size={12} aria-hidden="true" />
                        </button>
                        <span className="text-muted">to</span>
                        <label htmlFor={`rw-end-${i}`} className="sr-only">Region {i + 1} end, in seconds</label>
                        <input
                          id={`rw-end-${i}`}
                          type="number" min={0} step={0.1} value={b.end ?? ''}
                          onChange={(e) => updateBoxTime(i, 'end', e.target.value)}
                          className="input-field w-20 py-1.5 px-2"
                        />
                        <span className="readout">sec</span>
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </section>

            {/* Options */}
            <div className="space-y-6 min-w-0">
              <section aria-labelledby="rw-erase-heading" className="card p-5 sm:p-6 space-y-4">
                <div>
                  <h3 id="rw-erase-heading" className="font-display text-lg text-ink">Erase quality</h3>
                  <p className="text-sm text-muted mt-1">
                    The old text is found automatically; only the letters are erased, and what was behind them is
                    rebuilt from the neighbouring frames. Text parked for seconds on a moving face can still leave a
                    soft patch, so preview before running the whole clip.
                  </p>
                </div>
                <SegmentedControl
                  options={[
                    { value: 'smart', label: 'Smart', hint: 'Recommended' },
                    { value: 'legacy', label: 'Fast', hint: 'Old method' },
                  ]}
                  value={eraseMode}
                  onChange={(v) => { setEraseMode(v); setPreview(null); }}
                />
                <p className="text-sm text-ink2">
                  {eraseMode === 'smart'
                    ? 'Letters only: the background is rebuilt from other frames.'
                    : 'Blurs the whole box: quicker, but leaves a visible smear.'}
                </p>

                <div className="border-t border-rule pt-4 space-y-3">
                  <button
                    type="button"
                    onClick={startPreview}
                    disabled={preview?.status === 'running' || boxes.length === 0}
                    className="btn-ghost w-full sm:w-auto"
                    title="Erase 3 seconds around the current video time and show before / after"
                  >
                    {previewRunning ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <Eye size={14} aria-hidden="true" />}
                    {previewRunning ? 'Rendering preview (~30 s)…' : `Preview 3 s around ${fmtTime(currentTime)}`}
                  </button>
                  <p className="sr-only" aria-live="polite">
                    {previewRunning ? 'Rendering the preview…' : preview?.status === 'done' ? 'Preview ready.' : ''}
                  </p>
                  {preview?.status === 'failed' && (
                    <p role="alert" className="text-sm text-ink2 flex items-start gap-2">
                      <AlertCircle size={16} className="text-danger shrink-0 mt-0.5" aria-hidden="true" />
                      <span className="break-words">{preview.error}</span>
                    </p>
                  )}
                  {preview?.status === 'done' && (
                    <figure className="space-y-1.5">
                      <div className="flex justify-around readout" aria-hidden="true">
                        <span>Before</span><span>After</span>
                      </div>
                      <video
                        key={preview.url}
                        src={preview.url}
                        className="w-full rounded-input bg-black border border-rule2 block"
                        autoPlay loop muted playsInline controls
                        aria-label="Erase preview, before and after"
                      />
                    </figure>
                  )}
                </div>
              </section>

              <section aria-labelledby="rw-dub-heading" className="card p-5 sm:p-6 space-y-3">
                <h3 id="rw-dub-heading" className="font-display text-lg text-ink">Dub voice</h3>
                <label htmlFor="rw-dub" className="sr-only">Dub language</label>
                <select
                  id="rw-dub"
                  value={targetLanguage}
                  onChange={(e) => setTargetLanguage(e.target.value)}
                  className="input-field cursor-pointer"
                  aria-describedby="rw-dub-help"
                >
                  <option value="">Original voice (no dub)</option>
                  {Object.entries(LANGUAGES).sort((a, b) => a[1].localeCompare(b[1])).map(([code, name]) => (
                    <option key={code} value={code}>{name}</option>
                  ))}
                </select>
                <p id="rw-dub-help" className="text-sm text-muted">
                  Replaces the voice with an AI dub. Want captions in another language instead, with the voice
                  unchanged? Do that afterwards with “Translate captions” in the subtitles tool; it works on any clip.
                </p>
              </section>

              {/* Small, deliberately-imperfect variations: a platform's
                  duplicate/recycled-content check is frame-hash-based, not
                  semantic, so a flip/speed/zoom/color nudge changes the file's
                  fingerprint without being visible to a viewer. */}
              <section aria-labelledby="rw-vary-heading" className="card p-5 sm:p-6 space-y-5">
                <div className="flex items-baseline justify-between gap-3">
                  <h3 id="rw-vary-heading" className="font-display text-lg text-ink">Vary the edit</h3>
                  <span className="readout">Optional</span>
                </div>

                <label htmlFor="rw-flip" className="flex items-center justify-between gap-4 cursor-pointer min-h-[44px]">
                  <span className="text-sm text-ink">Flip horizontally</span>
                  <span className="relative inline-flex items-center shrink-0">
                    <input
                      id="rw-flip"
                      type="checkbox"
                      role="switch"
                      checked={flip}
                      onChange={(e) => setFlip(e.target.checked)}
                      className="sr-only peer"
                    />
                    <span
                      aria-hidden="true"
                      className="block w-10 h-6 rounded-full border border-rule2 bg-paper3 transition-colors peer-checked:bg-ink peer-checked:border-ink peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-[color:var(--color-focus)]"
                    />
                    <span
                      aria-hidden="true"
                      className="absolute left-1 top-1 w-4 h-4 rounded-full bg-muted transition-transform peer-checked:translate-x-4 peer-checked:bg-paper"
                    />
                  </span>
                </label>

                <div className="grid sm:grid-cols-3 gap-5">
                  <div>
                    <div className="flex items-baseline justify-between mb-2">
                      <label htmlFor="rw-speed" className="text-sm text-ink">Speed</label>
                      <span className="readout">{Math.round(speed * 100)}%</span>
                    </div>
                    <input id="rw-speed" type="range" min="0.95" max="1.05" step="0.01" value={speed} onChange={(e) => setSpeed(Number(e.target.value))} className="w-full accent-ink" />
                  </div>
                  <div>
                    <div className="flex items-baseline justify-between mb-2">
                      <label htmlFor="rw-zoom" className="text-sm text-ink">Zoom</label>
                      <span className="readout">{Math.round(zoom * 100)}%</span>
                    </div>
                    <input id="rw-zoom" type="range" min="1.0" max="1.15" step="0.01" value={zoom} onChange={(e) => setZoom(Number(e.target.value))} className="w-full accent-ink" />
                  </div>
                  <div>
                    <div className="flex items-baseline justify-between mb-2">
                      <label htmlFor="rw-color" className="text-sm text-ink">Color</label>
                      <span className="readout">{Math.round(colorBoost * 100)}%</span>
                    </div>
                    <input id="rw-color" type="range" min="1.0" max="1.2" step="0.01" value={colorBoost} onChange={(e) => setColorBoost(Number(e.target.value))} className="w-full accent-ink" />
                  </div>
                </div>
              </section>
            </div>
          </div>

          {errorNearActions && errorBox}

          <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-3 border-t border-rule2 pt-5">
            <button type="button" onClick={reset} className="btn-ghost">Cancel</button>
            <button type="button" onClick={handleSubmit} className="btn-accent">
              <Eraser size={16} aria-hidden="true" /> Erase and open in editor
            </button>
          </div>
        </div>
      )}

      {/* ===== 3 · Result ===== */}
      {stage === 'processing' && (
        <section aria-labelledby="rw-result-heading" className="card-print p-5 sm:p-7 space-y-5">
          <div className="flex items-start gap-4">
            <Loader2 size={22} className="animate-spin text-muted shrink-0 mt-1" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <h3 id="rw-result-heading" className="font-display text-xl text-ink">Erasing the old text</h3>
              <p className="text-sm text-muted mt-1">This can take a minute. The clip opens in the editor as soon as it is done.</p>
            </div>
            <p className="font-quote text-5xl leading-none text-ink shrink-0" aria-hidden="true">
              {progress}<span className="text-2xl text-muted">%</span>
            </p>
          </div>
          <div
            role="progressbar"
            aria-label="Erasing progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={progress}
            className="h-1.5 rounded-full bg-paper3 overflow-hidden"
          >
            <div className="h-full bg-ink transition-all duration-500" style={{ width: `${progress}%` }} />
          </div>
          <div>
            <p id="rw-log-label" className="readout mb-2">Log</p>
            <div
              role="log"
              aria-live="polite"
              aria-labelledby="rw-log-label"
              className="tray p-4 max-h-64 overflow-y-auto custom-scrollbar font-mono text-xs text-ink2 space-y-1 break-words"
            >
              {logs.map((l, i) => <div key={i}>{l}</div>)}
            </div>
          </div>
        </section>
      )}

      {stage === 'error' && (
        <section aria-labelledby="rw-error-heading" className="card p-6 sm:p-8 text-center space-y-4">
          <h3 id="rw-error-heading" className="font-display text-xl text-ink">The clip could not be processed</h3>
          <p className="text-sm text-muted">The reason is shown above. Upload the clip again to retry.</p>
          <button type="button" onClick={reset} className="btn-primary">Try again</button>
        </section>
      )}
    </div>
  );
}
