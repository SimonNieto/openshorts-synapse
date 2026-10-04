import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Loader2, RefreshCw, ThumbsUp, ThumbsDown, Images, X, Check } from 'lucide-react';
import { getApiUrl } from '../config';
import { apiJson } from '../lib/api';

const FILTERS = [
    { id: 'all', label: 'toutes' },
    { id: 'todo', label: 'à noter' },
    { id: 'kept', label: 'gardées' },
    { id: 'refused', label: 'refusées' },
    { id: 'up', label: '👍' },
    { id: 'down', label: '👎' },
];
const SOURCES = [
    { id: 'all', label: 'tout' },
    { id: 'job', label: 'jobs' },
    { id: 'bench', label: 'banc' },
];

/**
 * B-roll gallery (4-oct-2026): every drawn picture the jobs made (their trace) and the drawn bench made, kept or
 * refused by the safety verifier, with the owner's verdict on each — 👍 / 👎, why, and what to change. The verdicts
 * go to output/_lessons/gallery_feedback.jsonl: the work on the images' principles reads them; no call does by itself.
 */
export default function BrollGallery() {
    const [pictures, setPictures] = useState(null);
    const [filter, setFilter] = useState('all');
    const [source, setSource] = useState('all');
    const [drafts, setDrafts] = useState({});      // id -> { verdict, why, change }
    const [busy, setBusy] = useState(null);
    const [saved, setSaved] = useState(null);
    const [error, setError] = useState('');
    const [zoom, setZoom] = useState(null);

    const load = useCallback(async () => {
        setError('');
        try {
            const d = await apiJson('/api/broll/gallery');
            setPictures(d.pictures || []);
        } catch (e) {
            setError(e.detail || 'Impossible de charger les images.');
            setPictures([]);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const draftOf = (p) => ({
        verdict: p.feedback?.verdict || '', why: p.feedback?.why || '', change: p.feedback?.change || '',
        ...(drafts[p.id] || {}),
    });
    const patch = (id, changes) => setDrafts((d) => ({ ...d, [id]: { ...(d[id] || {}), ...changes } }));

    const save = async (p, verdict) => {
        const d = { ...draftOf(p), ...(verdict !== undefined ? { verdict } : {}) };
        setBusy(p.id);
        setError('');
        try {
            const r = await apiJson('/api/broll/gallery/feedback', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: p.id, verdict: d.verdict, why: d.why, change: d.change }),
            });
            setPictures((list) => list.map((x) => (x.id === p.id ? { ...x, feedback: r.feedback } : x)));
            setDrafts((all) => { const n = { ...all }; delete n[p.id]; return n; });
            setSaved(p.id);
            setTimeout(() => setSaved((s) => (s === p.id ? null : s)), 1500);
        } catch (e) {
            setError(e.detail || e.message);
        } finally {
            setBusy(null);
        }
    };

    const shown = useMemo(() => (pictures || []).filter((p) => {
        if (source !== 'all' && p.source !== source) return false;
        if (filter === 'todo') return !p.feedback;
        if (filter === 'kept') return p.status === 'kept';
        if (filter === 'refused') return p.status !== 'kept';
        if (filter === 'up' || filter === 'down') return p.feedback?.verdict === filter;
        return true;
    }), [pictures, filter, source]);

    const counts = useMemo(() => {
        const all = pictures || [];
        return {
            all: all.length, todo: all.filter((p) => !p.feedback).length,
            up: all.filter((p) => p.feedback?.verdict === 'up').length,
            down: all.filter((p) => p.feedback?.verdict === 'down').length,
        };
    }, [pictures]);

    return (
        <div className="h-full overflow-y-auto p-4 sm:p-6 md:p-8 max-w-6xl mx-auto animate-fade">
            <p className="eyebrow mb-1.5">13 · IMAGES B-ROLL</p>
            <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
                <h1 className="font-display lowercase text-2xl text-ink">Images B-roll</h1>
                <button type="button" onClick={load} disabled={!!busy} className="btn-quiet px-3 py-1.5 text-xs inline-flex items-center gap-1.5">
                    <RefreshCw size={13} /> actualiser
                </button>
            </div>
            <p className="text-muted text-sm mb-4">
                Toutes les images dessinées par les jobs et par le banc, gardées ou refusées par le vérificateur. Mets 👍 ou 👎,
                écris pourquoi et ce que tu veux changer : c’est ce qui sert à affiner les principes des images.
                {' '}{counts.all} images · {counts.todo} à noter · {counts.up} 👍 · {counts.down} 👎
            </p>

            <div className="flex flex-wrap items-center gap-2 mb-5">
                {FILTERS.map((f) => (
                    <button key={f.id} type="button" onClick={() => setFilter(f.id)}
                        className={`${filter === f.id ? 'btn-primary' : 'btn-quiet'} px-3 py-1 text-xs`}>
                        {f.label}
                    </button>
                ))}
                <span className="text-muted text-xs mx-1">·</span>
                {SOURCES.map((s) => (
                    <button key={s.id} type="button" onClick={() => setSource(s.id)}
                        className={`${source === s.id ? 'btn-primary' : 'btn-quiet'} px-3 py-1 text-xs`}>
                        {s.label}
                    </button>
                ))}
            </div>

            {error && <p className="text-xs text-danger mb-4">{error}</p>}

            {pictures === null && (
                <div className="py-16 text-center text-muted"><Loader2 size={22} className="animate-spin mx-auto" /></div>
            )}

            {pictures && shown.length === 0 && !error && (
                <div className="text-center py-20 text-muted">
                    <Images size={40} className="mx-auto mb-4" />
                    <p>Aucune image ici. Elles apparaissent après un job (et après un banc dessin).</p>
                </div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {shown.map((p, i, list) => {
                    const d = draftOf(p);
                    const heading = i === 0 || list[i - 1].group !== p.group;
                    const dirty = p.feedback
                        ? d.verdict !== p.feedback.verdict || d.why !== p.feedback.why || d.change !== p.feedback.change
                        : !!(d.verdict || d.why || d.change);
                    const working = busy === p.id;
                    return (
                        <React.Fragment key={p.id}>
                            {heading && <p className="eyebrow lg:col-span-2 mt-3">{p.group}</p>}
                            <div className={`p-3 rounded-input border ${p.status === 'kept' ? 'border-rule' : 'border-danger/60'} space-y-2`}>
                                <div className="relative">
                                    <img
                                        src={getApiUrl(`/api/broll/gallery/image?id=${encodeURIComponent(p.id)}`)}
                                        alt={p.idea || p.said}
                                        loading="lazy"
                                        onClick={() => setZoom(p)}
                                        className={`w-full rounded-input bg-paper3 cursor-zoom-in ${p.layout === 'hero' ? 'max-h-96 object-contain' : 'object-cover aspect-video'} ${p.status === 'kept' ? '' : 'opacity-70'}`}
                                    />
                                    <span className={`absolute top-2 left-2 text-[11px] px-2 py-0.5 rounded-full ${p.status === 'kept' ? 'bg-ink/70 text-paper' : 'bg-danger text-paper'}`}>
                                        {p.status === 'kept' ? (p.layout === 'hero' ? 'gardée · plein écran' : 'gardée') : 'refusée'}
                                    </span>
                                </div>
                                <p className="text-sm text-ink">« {p.said} »</p>
                                {p.idea && <p className="text-[12px] text-muted">idée : {p.idea}</p>}
                                {p.why && <p className="text-[12px] text-danger">refusée : {p.why}</p>}
                                <div className="flex items-center gap-2">
                                    <button type="button" disabled={working} onClick={() => save(p, d.verdict === 'up' ? '' : 'up')}
                                        className={`${d.verdict === 'up' ? 'btn-primary' : 'btn-quiet'} px-3 py-1 text-xs inline-flex items-center gap-1.5`}>
                                        <ThumbsUp size={14} /> j’aime
                                    </button>
                                    <button type="button" disabled={working} onClick={() => patch(p.id, { verdict: d.verdict === 'down' ? '' : 'down' })}
                                        className={`${d.verdict === 'down' ? 'btn-primary' : 'btn-quiet'} px-3 py-1 text-xs inline-flex items-center gap-1.5`}>
                                        <ThumbsDown size={14} /> j’aime pas
                                    </button>
                                    {working && <Loader2 size={14} className="animate-spin text-muted" />}
                                    {saved === p.id && <Check size={14} className="text-ink" />}
                                </div>
                                {(d.verdict || d.why || d.change) && (
                                    <div className="space-y-2">
                                        <textarea rows={2} value={d.why} disabled={working}
                                            onChange={(e) => patch(p.id, { why: e.target.value })}
                                            placeholder="pourquoi ?"
                                            className="input-field text-xs w-full py-1 px-2 resize-y" />
                                        <textarea rows={2} value={d.change} disabled={working}
                                            onChange={(e) => patch(p.id, { change: e.target.value })}
                                            placeholder="ce que je veux changer dedans"
                                            className="input-field text-xs w-full py-1 px-2 resize-y" />
                                        <button type="button" disabled={working || !dirty} onClick={() => save(p)}
                                            className="btn-primary px-3 py-1 text-xs">
                                            enregistrer
                                        </button>
                                    </div>
                                )}
                                <details className="text-[11px] text-muted">
                                    <summary className="cursor-pointer">prompt et graine</summary>
                                    <p className="mt-1 break-words">{p.prompt}</p>
                                    <p className="mt-1">graine {p.seed ?? '—'} · {p.date}</p>
                                </details>
                            </div>
                        </React.Fragment>
                    );
                })}
            </div>

            {zoom && (
                <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4" onClick={() => setZoom(null)}>
                    <button type="button" className="absolute top-4 right-4 text-white" onClick={() => setZoom(null)} aria-label="fermer">
                        <X size={28} />
                    </button>
                    <img src={getApiUrl(`/api/broll/gallery/image?id=${encodeURIComponent(zoom.id)}`)} alt={zoom.idea || zoom.said}
                        className="max-h-full max-w-full rounded-input" />
                </div>
            )}
        </div>
    );
}
