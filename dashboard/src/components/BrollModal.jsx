import React, { useState, useEffect } from 'react';
import { Loader2, Trash2, RefreshCw, Check, ThumbsUp, ThumbsDown } from 'lucide-react';
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
            eyebrow="b-roll"
            title="check the images"
            size="lg"
            footer={(
                <div className="flex items-center justify-between gap-3 px-4 sm:px-6 py-3">
                    <span className="text-xs text-muted">{keptCount} of {items.length} kept</span>
                    <button type="button" onClick={apply} disabled={!!busy} className="btn-primary px-4 py-2 text-sm inline-flex items-center gap-2">
                        {busy === 'apply' ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
                        {busy === 'apply' ? 'cutting in…' : 'cut them in'}
                    </button>
                </div>
            )}
        >
            {error && <p className="text-xs text-red-400 mb-3">{error}</p>}
            {items.length === 0 && <p className="text-sm text-muted">No image was prepared for this clip.</p>}
            {items.length > 0 && (
                <div className="flex flex-wrap items-center gap-2 mb-3 p-2.5 rounded-input border border-rule text-xs">
                    <span className="text-muted inline-flex items-center gap-1">
                        every image stays
                        <input type="number" step="0.1" min={DUR_MIN} max={DUR_MAX} value={allDur}
                            onChange={(e) => setAllDur(e.target.value)}
                            onKeyDown={(e) => { if (e.key === 'Enter') setDurAll(); }}
                            className="input-field text-xs py-0.5 px-1.5 w-16" />
                        s
                    </span>
                    <button type="button" onClick={setDurAll} disabled={!!busy} className="btn-quiet px-2.5 py-1 text-xs">
                        apply to all
                    </button>
                    <span className="text-muted">({DUR_MIN}–{DUR_MAX} s)</span>
                </div>
            )}
            <div className="space-y-3">
                {items.map((it) => (
                    <div key={it.image} className={`flex gap-3 p-2.5 rounded-input border border-rule ${it._keep ? '' : 'opacity-40'}`}>
                        <img src={getApiUrl(`/videos/${jobId}/${it.image}`)} alt={it.anchor}
                            className="w-24 h-24 sm:w-28 sm:h-28 object-cover rounded-input bg-paper3 shrink-0" />
                        <div className="grow min-w-0 space-y-1.5">
                            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                                {isScreen(it)
                                    ? <span className="readout px-1.5 py-0.5 rounded bg-brass/15 text-brass">shown in the source video</span>
                                    : <span className="text-ink font-medium">“{it.anchor}”</span>}
                                {it.layout === 'hero' && <span className="readout px-1.5 py-0.5 rounded bg-brass/15 text-brass">full screen</span>}
                                {it.layout === 'card' && <span className="readout px-1.5 py-0.5 rounded bg-paper3 text-ink2">wide card</span>}
                                <label className="text-muted inline-flex items-center gap-1">
                                    at
                                    <input type="number" step="0.1" min="0" value={it.t}
                                        onChange={(e) => patch(it.image, { t: e.target.value })}
                                        className="input-field text-xs py-0.5 px-1.5 w-16" />
                                    s
                                </label>
                                <label className="text-muted inline-flex items-center gap-1">
                                    for
                                    <input type="number" step="0.1" min={DUR_MIN} max={isScreen(it) ? SCREEN_DUR_MAX : DUR_MAX} value={it.dur}
                                        onChange={(e) => patch(it.image, { dur: e.target.value })}
                                        onBlur={(e) => patch(it.image, { dur: clampDur(e.target.value, it) })}
                                        className="input-field text-xs py-0.5 px-1.5 w-16" />
                                    s
                                </label>
                                <span className="text-muted">{it.source}</span>
                            </div>
                            {!isScreen(it) && (
                                <textarea rows={2} value={it.prompt || ''} onChange={(e) => patch(it.image, { prompt: e.target.value })}
                                    placeholder="what the image shows"
                                    className="input-field text-xs w-full py-1 px-2 resize-none" />
                            )}
                            <div className="flex flex-wrap items-center gap-2">
                                {!isScreen(it) && (
                                    <select value={it.style || 'photo'} onChange={(e) => patch(it.image, { style: e.target.value })}
                                        className="input-field text-xs py-1 px-2">
                                        {STYLE_OPTS.map((s) => <option key={s} value={s}>{s}</option>)}
                                    </select>
                                )}
                                {!isScreen(it) && (
                                    <button type="button" onClick={() => redo(it)} disabled={!!busy} className="btn-quiet px-2.5 py-1 text-xs inline-flex items-center gap-1.5">
                                        {busy === it.image ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                                        redo
                                    </button>
                                )}
                                {!isScreen(it) && (
                                    <>
                                        <button type="button" onClick={() => feedback(it, 'up')} disabled={!!busy}
                                            title="Bien vu : la chaîne retient ce niveau"
                                            className={`btn-quiet px-2 py-1 text-xs inline-flex items-center ${fb[it.image] === 'up' ? 'text-green-500' : ''}`}>
                                            <ThumbsUp size={13} />
                                        </button>
                                        <button type="button" onClick={() => feedback(it, 'down')} disabled={!!busy}
                                            title="Mauvaise image : dis pourquoi, la chaîne apprend"
                                            className={`btn-quiet px-2 py-1 text-xs inline-flex items-center ${fb[it.image] === 'down' ? 'text-red-500' : ''}`}>
                                            <ThumbsDown size={13} />
                                        </button>
                                    </>
                                )}
                                <button type="button" onClick={() => patch(it.image, { _keep: !it._keep })} disabled={!!busy}
                                    className="btn-quiet px-2.5 py-1 text-xs inline-flex items-center gap-1.5">
                                    <Trash2 size={13} />
                                    {it._keep ? 'remove' : 'put back'}
                                </button>
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </Modal>
    );
}
