import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Loader2, RotateCcw, AlertCircle, Play, Pause, Columns2 } from 'lucide-react';
import { getApiUrl } from '../config';
import { apiJson } from '../lib/api';
import Modal from './ui/Modal';

// Manual reframing: the automatic crop is right most of the time and grossly
// wrong occasionally, and until now there was no way to say "frame it here".
//
// The unit is the scene, because a podcast cuts between a fixed close camera
// and a fixed wide one and the right crop differs per camera. Scenes the user
// does not touch stay automatic, so fixing one bad shot cannot spoil the good
// ones — only adjusted scenes are sent.
//
// Two things a still frame cannot tell you, and both are handled here:
//   - WHO is talking. Each scene plays its own range of an uncropped preview,
//     with sound, and the rectangle stays overlaid while it plays.
//   - Whether one window is even enough. A scene can be split into two stacked
//     regions, positioned independently.

const fmt = (s) => {
    const m = Math.floor(s / 60);
    const r = Math.floor(s % 60);
    return `${m}:${String(r).padStart(2, '0')}`;
};

// 36px square icon button, 44px on touch screens.
const ICON_BTN = 'inline-flex items-center justify-center shrink-0 w-9 h-9 [@media(pointer:coarse)]:w-11 [@media(pointer:coarse)]:h-11 rounded-input border transition-colors duration-200';

export default function ReframeEditor({ jobId, clipIndex, clipTitle, onClose, onReframed }) {
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [data, setData] = useState(null);
    const [overrides, setOverrides] = useState({});   // idx -> number | {top,bottom}
    const [playing, setPlaying] = useState(null);     // scene index being played
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        let alive = true;
        (async () => {
            try {
                const res = await apiJson(`/api/clip/${jobId}/${clipIndex}/scenes`);
                if (!alive) return;
                setData(res);
                // Start from what is already applied. A re-render rebuilds
                // from source with only what it receives, so opening blank
                // would quietly discard every earlier adjustment on the next
                // save.
                const salvos = res.saved_overrides || {};
                setOverrides(Object.fromEntries(
                    Object.entries(salvos).map(([k, v]) => [Number(k), v])
                ));
            } catch (e) {
                if (alive) setError(e?.message || 'Could not read the scenes of this clip.');
            } finally {
                if (alive) setLoading(false);
            }
        })();
        return () => { alive = false; };
    }, [jobId, clipIndex]);

    const half = (data?.crop_width_fraction ?? 0.5) / 2;
    const clamp = useCallback((v) => Math.min(1 - half, Math.max(half, v)), [half]);

    // What a scene shows right now: the user's value, else the backend's
    // suggestion (the biggest face in the shot).
    const valueOf = useCallback((scene) => (
        overrides[scene.index] ?? clamp(scene.suggested_center)
    ), [overrides, clamp]);

    const setSingle = useCallback((idx, fraction) => {
        setOverrides((o) => ({ ...o, [idx]: clamp(fraction) }));
    }, [clamp]);

    const setSplitHalf = useCallback((idx, which, fraction) => {
        setOverrides((o) => {
            const cur = o[idx];
            const base = (cur && typeof cur === 'object')
                ? cur
                : { top: { x: clamp(0.3), y: 0.5 }, bottom: { x: clamp(0.7), y: 0.5 } };
            const anterior = base[which] || { y: 0.5 };
            return { ...o, [idx]: {
                ...base,
                [which]: { x: clamp(fraction), y: anterior.y ?? 0.5 },
            } };
        });
    }, [clamp]);

    const toggleSplit = useCallback((idx, scene) => {
        setOverrides((o) => {
            const cur = o[idx];
            if (cur && typeof cur === 'object') {
                // back to a single window, kept where the top half was
                return { ...o, [idx]: cur.top?.x ?? 0.5 };
            }
            const centre = typeof cur === 'number' ? cur : clamp(scene.suggested_center);
            // SPLIT halves crop vertically as well, so each carries the face
            // height the backend measured for this scene.
            const y = scene.suggested_center_y ?? 0.5;
            return { ...o, [idx]: {
                top: { x: clamp(centre - 0.2), y },
                bottom: { x: clamp(centre + 0.2), y },
            } };
        });
    }, [clamp]);

    const resetScene = useCallback((idx) => {
        setOverrides((o) => {
            const next = { ...o };
            delete next[idx];
            return next;
        });
    }, []);

    const adjusted = Object.keys(overrides).length;

    const handleSave = async () => {
        if (!adjusted || saving) return;
        setSaving(true);
        setError(null);
        try {
            const payload = Object.fromEntries(Object.entries(overrides).map(([k, v]) => [
                String(k),
                typeof v === 'object'
                    ? { top: { x: Number(v.top.x.toFixed(4)), y: Number(v.top.y.toFixed(4)) },
                        bottom: { x: Number(v.bottom.x.toFixed(4)), y: Number(v.bottom.y.toFixed(4)) } }
                    : Number(v.toFixed(4)),
            ]));
            const res = await apiJson('/api/clip/reframe', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ job_id: jobId, clip_index: clipIndex, crop_overrides: payload }),
            });
            if (onReframed) onReframed(clipIndex, res);
            onClose();
        } catch (e) {
            setError(e?.message || 'The re-render failed.');
        } finally {
            setSaving(false);
        }
    };

    const footer = (
        <div className="flex flex-wrap items-center justify-end gap-2">
            <p className="w-full sm:w-auto sm:mr-auto font-mono text-xs text-ink2" aria-live="polite">
                {saving
                    ? 'Re-rendering the clip…'
                    : adjusted === 0
                        ? 'Nothing adjusted yet'
                        : `${adjusted} scene${adjusted > 1 ? 's' : ''} reframed by hand`}
            </p>
            <button type="button" onClick={onClose} className="btn-ghost flex-1 sm:flex-none">Cancel</button>
            <button
                type="button"
                onClick={handleSave}
                disabled={!adjusted || saving}
                className="btn-accent flex-[2] sm:flex-none"
            >
                {saving ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : null}
                {saving ? 'Re-rendering…' : 'Apply reframing'}
            </button>
        </div>
    );

    return (
        /* The shared Modal: a bottom sheet on a phone, a centred dialog from sm. */
        <Modal isOpen onClose={onClose} size="xl" title="Reframe the scenes" footer={footer} dismissOnOverlay={false}>
            <div className="space-y-5">
                <div className="min-w-0 space-y-1">
                    {clipTitle && <p className="text-sm text-ink truncate">{clipTitle}</p>}
                    <p className="text-sm text-muted leading-relaxed max-w-prose">
                        Play a scene to hear who is talking, then drag the frame over the
                        person you want — or focus it and use the arrow keys. Each scene is
                        one camera; the ones you leave alone keep the automatic framing.
                    </p>
                </div>

                {loading && (
                    <div role="status" className="tray flex items-center justify-center gap-2 text-sm text-ink2 py-10">
                        <Loader2 size={18} className="animate-spin text-muted" aria-hidden="true" />
                        Reading the scenes…
                    </div>
                )}

                {error && (
                    <div role="alert" className="flex items-start gap-2 text-sm text-danger border border-danger/40 rounded-input px-3 py-2">
                        <AlertCircle size={16} className="shrink-0 mt-0.5" aria-hidden="true" />
                        <span>{error}</span>
                    </div>
                )}

                {data?.scenes?.length > 0 && (
                    <ul className="grid gap-x-6 gap-y-8 lg:grid-cols-2">
                        {data.scenes.map((scene) => (
                            <SceneRow
                                key={scene.index}
                                scene={scene}
                                value={valueOf(scene)}
                                widthFraction={data.crop_width_fraction}
                                previewUrl={data.preview_url}
                                touched={scene.index in overrides}
                                playing={playing === scene.index}
                                onPlayToggle={() => setPlaying((p) => (p === scene.index ? null : scene.index))}
                                onMoveSingle={(f) => setSingle(scene.index, f)}
                                onMoveHalf={(which, f) => setSplitHalf(scene.index, which, f)}
                                onToggleSplit={() => toggleSplit(scene.index, scene)}
                                onReset={() => resetScene(scene.index)}
                            />
                        ))}
                    </ul>
                )}
            </div>
        </Modal>
    );
}


// One scene. While it plays, the frame is replaced by the uncropped preview
// seeked to this scene, so the rectangle can be judged against moving pictures
// and sound rather than a single still.
function SceneRow({ scene, value, widthFraction, previewUrl, touched, playing,
                    onPlayToggle, onMoveSingle, onMoveHalf, onToggleSplit, onReset }) {
    const boxRef = useRef(null);
    const videoRef = useRef(null);
    const [dragging, setDragging] = useState(null);   // null | 'single' | 'top' | 'bottom'

    const isSplit = value && typeof value === 'object';

    // Play only this scene's slice of the shared preview.
    useEffect(() => {
        const v = videoRef.current;
        if (!v) return;
        if (!playing) { v.pause(); return; }
        v.currentTime = scene.start;
        v.play().catch(() => {});
        const stopAtEnd = () => { if (v.currentTime >= scene.end) { v.pause(); } };
        v.addEventListener('timeupdate', stopAtEnd);
        return () => v.removeEventListener('timeupdate', stopAtEnd);
    }, [playing, scene.start, scene.end]);

    const fractionFromEvent = useCallback((clientX) => {
        const el = boxRef.current;
        if (!el) return 0.5;
        const rect = el.getBoundingClientRect();
        return (clientX - rect.left) / rect.width;
    }, []);

    useEffect(() => {
        if (!dragging) return;
        const move = (e) => {
            const x = e.touches ? e.touches[0].clientX : e.clientX;
            const f = fractionFromEvent(x);
            if (dragging === 'single') onMoveSingle(f);
            else onMoveHalf(dragging, f);
        };
        const up = () => setDragging(null);
        window.addEventListener('mousemove', move);
        window.addEventListener('mouseup', up);
        window.addEventListener('touchmove', move);
        window.addEventListener('touchend', up);
        return () => {
            window.removeEventListener('mousemove', move);
            window.removeEventListener('mouseup', up);
            window.removeEventListener('touchmove', move);
            window.removeEventListener('touchend', up);
        };
    }, [dragging, fractionFromEvent, onMoveSingle, onMoveHalf]);

    const startDrag = (which) => (e) => {
        e.stopPropagation();
        setDragging(which);
        const x = e.touches ? e.touches[0].clientX : e.clientX;
        if (which === 'single') onMoveSingle(fractionFromEvent(x));
        else onMoveHalf(which, fractionFromEvent(x));
    };

    // The keyboard way to do what the drag does: arrows nudge the window
    // (Shift for bigger steps), Home / End send it to either edge. The same
    // move callbacks clamp it to the frame.
    const nudge = (which, centre) => (e) => {
        const step = e.shiftKey ? 0.05 : 0.01;
        let next = null;
        if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') next = centre - step;
        else if (e.key === 'ArrowRight' || e.key === 'ArrowUp') next = centre + step;
        else if (e.key === 'Home') next = 0;
        else if (e.key === 'End') next = 1;
        if (next === null) return;
        e.preventDefault();
        if (which === 'single') onMoveSingle(next);
        else onMoveHalf(which, next);
    };

    const sceneName = `scene ${scene.index + 1}`;

    const win = (centre, label, which) => {
        const leftPct = (centre - widthFraction / 2) * 100;
        const pct = Math.round(centre * 100);
        return (
            <div
                key={which}
                role="slider"
                tabIndex={0}
                aria-label={label ? `${label} region, ${sceneName}` : `Crop frame, ${sceneName}`}
                aria-orientation="horizontal"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={pct}
                aria-valuetext={`${pct}% across the shot`}
                onMouseDown={startDrag(which)}
                onTouchStart={startDrag(which)}
                onKeyDown={nudge(which, centre)}
                className="absolute inset-y-0 border-2 border-ink cursor-ew-resize focus-visible:outline-offset-[-6px]"
                style={{ left: `${leftPct}%`, width: `${widthFraction * 100}%` }}
            >
                {label && (
                    <span className="absolute top-1.5 left-1.5 font-mono text-[10.5px] uppercase tracking-[0.08em] px-1.5 py-0.5 rounded-[4px] bg-ink text-paper2">
                        {label}
                    </span>
                )}
            </div>
        );
    };

    return (
        <li className="space-y-2 min-w-0">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2.5 min-w-0">
                    <button
                        type="button"
                        onClick={onPlayToggle}
                        aria-pressed={playing}
                        aria-label={playing ? `Pause ${sceneName}` : `Play ${sceneName} with sound`}
                        title="Play this scene with sound"
                        className={`${ICON_BTN} ${playing ? 'border-ink bg-ink text-paper2' : 'border-rule2 bg-paper3 text-ink hover:border-ink'}`}
                    >
                        {playing ? <Pause size={15} aria-hidden="true" /> : <Play size={15} aria-hidden="true" />}
                    </button>
                    <div className="min-w-0">
                        <h3 className="font-display text-sm text-ink leading-tight">Scene {scene.index + 1}</h3>
                        <p className="readout truncate">{fmt(scene.start)}–{fmt(scene.end)}</p>
                    </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                    <button
                        type="button"
                        onClick={onToggleSplit}
                        aria-pressed={!!isSplit}
                        title="Stack two regions instead of one window"
                        className={`inline-flex items-center gap-1.5 h-9 [@media(pointer:coarse)]:h-11 px-3 rounded-input border text-xs font-medium transition-colors duration-200 ${
                            isSplit ? 'border-ink bg-ink text-paper2' : 'border-rule2 text-ink2 hover:text-ink hover:border-ink'}`}
                    >
                        <Columns2 size={14} aria-hidden="true" /> Split
                    </button>
                    {touched ? (
                        <button
                            type="button"
                            onClick={onReset}
                            aria-label={`Reset ${sceneName} to the automatic framing`}
                            title="Go back to the automatic framing for this scene"
                            className="inline-flex items-center gap-1.5 h-9 [@media(pointer:coarse)]:h-11 px-3 rounded-input border border-rule2 text-xs font-medium text-ink2 hover:text-ink hover:border-ink transition-colors duration-200"
                        >
                            <RotateCcw size={14} aria-hidden="true" /> Reset
                        </button>
                    ) : (
                        <span className="readout px-1">Automatic</span>
                    )}
                </div>
            </div>

            <div
                ref={boxRef}
                className={`relative overflow-hidden rounded-input select-none bg-black border ${
                    touched ? 'border-ink/60' : 'border-rule2'}`}
            >
                {playing && previewUrl ? (
                    <video
                        ref={videoRef}
                        src={getApiUrl(previewUrl)}
                        playsInline
                        className="w-full block"
                    />
                ) : scene.thumbnail_url ? (
                    <img
                        src={getApiUrl(scene.thumbnail_url)}
                        alt=""
                        draggable={false}
                        className="w-full block pointer-events-none"
                    />
                ) : (
                    <div className="w-full aspect-video bg-black" />
                )}

                {/* Everything outside the kept region is dimmed, so what survives
                    the crop is what stays bright. */}
                {!isSplit && (
                    <>
                        <div className="absolute inset-y-0 left-0 bg-paper/70 pointer-events-none"
                             style={{ width: `${Math.max(0, (value - widthFraction / 2) * 100)}%` }} />
                        <div className="absolute inset-y-0 right-0 bg-paper/70 pointer-events-none"
                             style={{ width: `${Math.max(0, 100 - (value + widthFraction / 2) * 100)}%` }} />
                    </>
                )}

                {isSplit
                    ? [win(value.top.x, 'Top', 'top'), win(value.bottom.x, 'Bottom', 'bottom')]
                    : win(value, null, 'single')}
            </div>

            <p className="font-mono text-[11px] text-muted">
                {touched ? 'Framed by hand' : 'Automatic framing'}
                {isSplit ? ' · two stacked regions' : ''}
            </p>

            {isSplit && (
                <p className="text-xs text-muted leading-relaxed">
                    Two regions stacked in the vertical frame: <strong className="font-medium text-ink2">top</strong> above,
                    <strong className="font-medium text-ink2"> bottom</strong> below. Drag each one onto the person it should hold.
                </p>
            )}
        </li>
    );
}
