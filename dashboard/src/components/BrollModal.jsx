import React, { useState, useEffect, useId } from 'react';
import { Loader2, Trash2, RefreshCw, Check, ThumbsUp, ThumbsDown, AlertCircle, RotateCcw, ImageOff } from 'lucide-react';
import Modal from './ui/Modal';
import { getApiUrl } from '../config';
import { apiJson } from '../lib/api';

// Must mirror broll.py STYLES.
const STYLE_OPTS = ['photo', 'neon', 'drawing', 'cinematic', 'vintage', '3d', 'comic', 'diagram'];
// Time on screen: broll.py renders 1-4 s; RISE_DUR / SEG_DUR are its defaults when an item has none.
// The picture the source itself showed (source "screen", broll.SCREEN_DUR_MAX) may stay up to 12 s.
const DUR_MIN = 1, DUR_MAX = 4, SCREEN_DUR_MAX = 12, RISE_DUR = 1.9, SEG_DUR = 1.6;
const isScreen = (it) => it.source === 'screen';
const clampDur = (v, it) => {
    const n = Number(String(v).replace(',', '.'));
    const hi = it && isScreen(it) ? SCREEN_DUR_MAX : DUR_MAX;
    return Number.isFinite(n) ? Math.round(Math.min(hi, Math.max(DUR_MIN, n)) * 10) / 10 : 2;
};

// Small, compact numeric field; 44px tall on touch screens.
const NUM = 'input-field !w-[4.5rem] !py-1 !px-2 h-9 [@media(pointer:coarse)]:h-11 text-sm tabular-nums';
// Neutral mono chip (colour is kept for the one action of the sheet).
const CHIP = 'font-mono text-[10.5px] uppercase tracking-[0.08em] text-ink2 border border-rule2 rounded-[4px] px-1.5 py-0.5';

/**
 * Manual B-roll review: the images prepared for a clip, each with its word,
 * time, style and prompt. Remove the ones you do not want, redo one from a new
 * prompt / style, shift its time, then "cut them in" (the server rebuilds the
 * clip with the kept images).
 */
export default function BrollModal({ isOpen, onClose, jobId, index, clip, profileId, onApplied }) {
    const [items, setItems] = useState([]);
    const [busy, setBusy] = useState(null);   // image name being redone, or 'apply'
    const [error, setError] = useState(null);
    const [allDur, setAllDur] = useState('2');  // "every image" time on screen
    const uid = useId();

    useEffect(() => {
        if (isOpen) {
            const list = (clip.broll || []).filter((it) => it.image)
                .map((it) => ({ ...it, dur: it.dur ?? (it.layout === 'rise' ? RISE_DUR : SEG_DUR), _keep: true }));
            setItems(list);
            setAllDur(list.length ? String(list[0].dur) : '2');
            setError(null);
        }
    }, [isOpen, clip]);

    const patch = (image, changes) => setItems((list) => list.map((it) => (it.image === image ? { ...it, ...changes } : it)));
    // The owner's verdict on a picture (v22): a lesson the B-roll chain reads in its next calls (broll_lessons).
    // A thumbs-down may carry a short note — the most useful signal there is.
    const [fb, setFb] = useState({});
    const feedback = async (it, verdict) => {
        let note = '';
        if (verdict === 'down') {
            const typed = window.prompt('Pourquoi ? (facultatif, une ligne : ce qui ne va pas sur cette image)', '');
            if (typed === null) return;
            note = typed.trim();
        }
        try {
            await apiJson(`/api/clip/${jobId}/${index}/broll/feedback`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ image: it.image, verdict, note }),
            });
            setFb((m) => ({ ...m, [it.image]: verdict }));
        } catch (e) {
            setError(e.message || String(e));
        }
    };
    const setDurAll = () => {
        const d = clampDur(allDur);
        setAllDur(String(d));
        // The source's own picture keeps its own time: the source decided it, not the review.
        setItems((list) => list.map((it) => (isScreen(it) ? it : { ...it, dur: d })));
    };

    const redo = async (it) => {
        setBusy(it.image);
        setError(null);
        try {
            const data = await apiJson(`/api/clip/${jobId}/${index}/broll/regenerate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ image: it.image, prompt: it.prompt || it.anchor, style: it.style, profile_id: profileId || null }),
            });
            patch(it.image, { ...data.item, t: it.t, dur: it.dur, _keep: it._keep });
        } catch (e) {
            setError(e.detail || e.message);
        } finally {
            setBusy(null);
        }
    };

    const apply = async () => {
        setBusy('apply');
        setError(null);
        try {
            const kept = items.filter((it) => it._keep).map((it) => ({ image: it.image, t: Number(String(it.t).replace(',', '.')), dur: clampDur(it.dur, it) }));
            const data = await apiJson(`/api/clip/${jobId}/${index}/broll/apply`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items: kept, profile_id: profileId || null }),
            });
            onApplied?.(data);
            onClose();
        } catch (e) {
            setError(e.detail || e.message);
        } finally {
            setBusy(null);
        }
    };

    const keptCount = items.filter((it) => it._keep).length;

    return (
        <Modal
            isOpen={isOpen}
            onClose={busy ? undefined : onClose}
            title="Check the B-roll images"
            size="lg"
            footer={(
                <div className="flex flex-wrap items-center justify-end gap-2">
                    <p className="w-full sm:w-auto sm:mr-auto font-mono text-xs text-ink2 tabular-nums" aria-live="polite">
                        {keptCount} of {items.length} kept
                        {busy === 'apply' && <span className="sr-only"> · cutting the images into the clip</span>}
                    </p>
                    <button type="button" onClick={onClose} disabled={!!busy} className="btn-ghost flex-1 sm:flex-none">
                        Cancel
                    </button>
                    <button type="button" onClick={apply} disabled={!!busy} className="btn-accent flex-[2] sm:flex-none">
                        {busy === 'apply' ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <Check size={16} aria-hidden="true" />}
                        {busy === 'apply' ? 'Cutting in…' : 'Cut them in'}
                    </button>
                </div>
            )}
        >
            {error && (
                <p role="alert" className="mb-4 flex items-start gap-2 rounded-input border border-danger/40 px-3 py-2 text-sm text-danger">
                    <AlertCircle size={16} className="shrink-0 mt-0.5" aria-hidden="true" />
                    <span>{error}</span>
                </p>
            )}

            {items.length === 0 && (
                <div className="tray px-4 py-8 flex flex-col items-center gap-2 text-center">
                    <ImageOff size={18} className="text-muted" aria-hidden="true" />
                    <p className="text-sm text-ink2">No image was prepared for this clip.</p>
                </div>
            )}

            {items.length > 0 && (
                <div className="tray p-3 sm:p-4 mb-5 flex flex-wrap items-center gap-x-3 gap-y-2">
                    <label htmlFor={`${uid}-all`} className="text-sm text-ink2">Every image stays on screen for</label>
                    <span className="inline-flex items-center gap-1.5">
                        <input
                            id={`${uid}-all`}
                            type="number" step="0.1" min={DUR_MIN} max={DUR_MAX} value={allDur}
                            onChange={(e) => setAllDur(e.target.value)}
                            onKeyDown={(e) => { if (e.key === 'Enter') setDurAll(); }}
                            aria-describedby={`${uid}-all-hint`}
                            className={NUM}
                        />
                        <span className="text-sm text-muted" aria-hidden="true">s</span>
                    </span>
                    <button type="button" onClick={setDurAll} disabled={!!busy} className="btn-quiet">
                        Apply to all
                    </button>
                    <span id={`${uid}-all-hint`} className="font-mono text-[11px] text-muted">{DUR_MIN}–{DUR_MAX} s</span>
                </div>
            )}

            <ul className="divide-y divide-rule">
                {items.map((it) => {
                    const verdict = fb[it.image];
                    const redoing = busy === it.image;
                    return (
                        <li key={it.image} className="py-4 first:pt-0 last:pb-0 grid grid-cols-[6.5rem_minmax(0,1fr)] sm:grid-cols-[9rem_minmax(0,1fr)] gap-3 sm:gap-5">
                            {/* the image, framed on black with its mono caption */}
                            <figure className="space-y-1.5 min-w-0">
                                <div className="relative bg-black border border-rule2 rounded-input overflow-hidden">
                                    <img
                                        src={getApiUrl(`/videos/${jobId}/${it.image}`)}
                                        alt={it.anchor}
                                        className={`w-full aspect-square object-cover transition-opacity duration-200 ${it._keep ? '' : 'opacity-30 grayscale'}`}
                                    />
                                    {redoing && (
                                        <span className="absolute inset-0 grid place-items-center bg-paper/70" aria-hidden="true">
                                            <Loader2 size={18} className="animate-spin text-ink" />
                                        </span>
                                    )}
                                </div>
                                <figcaption className="readout truncate">
                                    {isScreen(it) ? 'Source frame' : (it.style || 'photo')}
                                </figcaption>
                            </figure>

                            <div className="min-w-0 space-y-3">
                                <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
                                    {isScreen(it)
                                        ? <span className="text-sm font-medium text-ink">Shown in the source video</span>
                                        : <p className="text-base text-ink leading-snug break-words">“{it.anchor}”</p>}
                                    {it.layout === 'hero' && <span className={CHIP}>Full screen</span>}
                                    {it.layout === 'card' && <span className={CHIP}>Wide card</span>}
                                    {!it._keep && <span className="badge-danger">Removed</span>}
                                </div>

                                <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
                                    <label className="inline-flex items-center gap-1.5 text-ink2">
                                        At
                                        <input
                                            type="number" step="0.1" min="0" value={it.t}
                                            onChange={(e) => patch(it.image, { t: e.target.value })}
                                            aria-label={`Start time of “${it.anchor || 'the source frame'}”, in seconds`}
                                            className={NUM}
                                        />
                                        <span className="text-muted" aria-hidden="true">s</span>
                                    </label>
                                    <label className="inline-flex items-center gap-1.5 text-ink2">
                                        For
                                        <input
                                            type="number" step="0.1" min={DUR_MIN} max={isScreen(it) ? SCREEN_DUR_MAX : DUR_MAX} value={it.dur}
                                            onChange={(e) => patch(it.image, { dur: e.target.value })}
                                            onBlur={(e) => patch(it.image, { dur: clampDur(e.target.value, it) })}
                                            aria-label={`Time on screen of “${it.anchor || 'the source frame'}”, in seconds`}
                                            className={NUM}
                                        />
                                        <span className="text-muted" aria-hidden="true">s</span>
                                    </label>
                                    <span className="readout">{it.source}</span>
                                </div>

                                {!isScreen(it) && (
                                    <div>
                                        <label htmlFor={`${uid}-${it.image}-prompt`} className="block text-xs font-medium text-ink2 mb-1">What the image shows</label>
                                        <textarea
                                            id={`${uid}-${it.image}-prompt`}
                                            rows={2} value={it.prompt || ''} onChange={(e) => patch(it.image, { prompt: e.target.value })}
                                            placeholder="Describe the picture"
                                            className="input-field text-sm w-full !py-2 !px-2.5 resize-none" />
                                    </div>
                                )}

                                <div className="flex flex-wrap items-center gap-2">
                                    {!isScreen(it) && (
                                        <>
                                            <label htmlFor={`${uid}-${it.image}-style`} className="sr-only">Image style</label>
                                            <select
                                                id={`${uid}-${it.image}-style`}
                                                value={it.style || 'photo'} onChange={(e) => patch(it.image, { style: e.target.value })}
                                                className="input-field !w-auto !py-1.5 !pl-2.5 !pr-8 h-9 [@media(pointer:coarse)]:h-11 text-sm">
                                                {STYLE_OPTS.map((s) => <option key={s} value={s}>{s}</option>)}
                                            </select>
                                        </>
                                    )}
                                    {!isScreen(it) && (
                                        <button type="button" onClick={() => redo(it)} disabled={!!busy} className="btn-quiet !py-1.5">
                                            {redoing ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <RefreshCw size={14} aria-hidden="true" />}
                                            {redoing ? 'Redoing…' : 'Redo'}
                                        </button>
                                    )}
                                    {!isScreen(it) && (
                                        <span className="inline-flex items-center gap-1" role="group" aria-label="Your verdict on this image">
                                            <button type="button" onClick={() => feedback(it, 'up')} disabled={!!busy}
                                                aria-pressed={verdict === 'up'}
                                                aria-label="Good image — the chain keeps this level"
                                                title="Good image — the chain keeps this level"
                                                className={`btn-quiet !px-2.5 !py-1.5 ${verdict === 'up' ? '!text-ok !border-ok/50' : ''}`}>
                                                <ThumbsUp size={14} aria-hidden="true" />
                                            </button>
                                            <button type="button" onClick={() => feedback(it, 'down')} disabled={!!busy}
                                                aria-pressed={verdict === 'down'}
                                                aria-label="Bad image — say why, the chain learns"
                                                title="Bad image — say why, the chain learns"
                                                className={`btn-quiet !px-2.5 !py-1.5 ${verdict === 'down' ? '!text-danger !border-danger/50' : ''}`}>
                                                <ThumbsDown size={14} aria-hidden="true" />
                                            </button>
                                        </span>
                                    )}
                                    <button type="button" onClick={() => patch(it.image, { _keep: !it._keep })} disabled={!!busy}
                                        className="btn-ghost !px-3 !py-1.5 sm:ml-auto">
                                        {it._keep ? <Trash2 size={14} aria-hidden="true" /> : <RotateCcw size={14} aria-hidden="true" />}
                                        {it._keep ? 'Remove' : 'Put back'}
                                    </button>
                                </div>
                            </div>
                        </li>
                    );
                })}
            </ul>
        </Modal>
    );
}
