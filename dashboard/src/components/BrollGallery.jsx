import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Loader2, RefreshCw, ThumbsUp, ThumbsDown, Images, X, Check, AlertCircle, Maximize2 } from 'lucide-react';
import { getApiUrl } from '../config';
import { apiJson } from '../lib/api';
import SegmentedControl from './ui/SegmentedControl';

const FILTERS = [
    { id: 'all', label: 'Toutes' },
    { id: 'todo', label: 'À noter' },
    { id: 'kept', label: 'Gardées' },
    { id: 'refused', label: 'Refusées' },
    { id: 'up', label: 'J’aime', icon: <ThumbsUp size={14} /> },
    { id: 'down', label: 'J’aime pas', icon: <ThumbsDown size={14} /> },
];
const SOURCES = [
    { id: 'all', label: 'Tout' },
    { id: 'job', label: 'Jobs' },
    { id: 'bench', label: 'Banc' },
];
// One `filter` value drives two controls: the picture's state, or my verdict on it.
const toOptions = (list) => list.map((f) => ({ value: f.id, label: f.label, icon: f.icon }));
const STATE_OPTIONS = toOptions(FILTERS.slice(0, 4));
const VERDICT_OPTIONS = toOptions(FILTERS.slice(4));
const SOURCE_OPTIONS = toOptions(SOURCES);

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

    // The zoom is a dialog: Escape closes it, and focus goes back where it was.
    useEffect(() => {
        if (!zoom) return undefined;
        const back = document.activeElement;
        // Tab stays on the close button, the dialog's only control.
        const onKey = (e) => {
            if (e.key === 'Escape') setZoom(null);
            else if (e.key === 'Tab') e.preventDefault();
        };
        window.addEventListener('keydown', onKey);
        return () => {
            window.removeEventListener('keydown', onKey);
            if (back && typeof back.focus === 'function') back.focus();
        };
    }, [zoom]);

    const verdictBtn = (active) => `w-10 h-10 [@media(pointer:coarse)]:w-11 [@media(pointer:coarse)]:h-11 rounded-input border inline-flex items-center justify-center transition-colors disabled:opacity-45 ${active
        ? 'bg-ink text-paper border-ink'
        : 'border-rule2 text-muted hover:text-ink hover:border-ink'}`;

    return (
        <div className="max-w-7xl mx-auto p-4 sm:p-8 space-y-8 animate-fade" lang="fr">
            <header className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between border-b border-rule pb-6">
                <div className="min-w-0">
                    <p className="eyebrow">Bibliothèque</p>
                    <h2 className="page-title mt-2">Images B-roll</h2>
                    <p className="page-lede mt-2">
                        Toutes les images dessinées par les jobs et par le banc, gardées ou refusées par le vérificateur. Dis si tu aimes ou pas,
                        écris pourquoi et ce que tu veux changer : c’est ce qui sert à affiner les principes des images.
                    </p>
                </div>
                <div className="flex flex-wrap items-end gap-x-6 gap-y-4 shrink-0">
                    <dl className="flex flex-wrap gap-x-6 gap-y-3">
                        <div>
                            <dt className="readout">Images</dt>
                            <dd className="font-quote text-3xl text-ink leading-none mt-1.5">{counts.all}</dd>
                        </div>
                        <div>
                            <dt className="readout">À noter</dt>
                            <dd className="font-quote text-3xl text-ink leading-none mt-1.5">{counts.todo}</dd>
                        </div>
                        <div>
                            <dt className="readout">J’aime</dt>
                            <dd className="font-quote text-3xl text-ink leading-none mt-1.5">{counts.up}</dd>
                        </div>
                        <div>
                            <dt className="readout">J’aime pas</dt>
                            <dd className="font-quote text-3xl text-ink leading-none mt-1.5">{counts.down}</dd>
                        </div>
                    </dl>
                    <button type="button" onClick={load} disabled={!!busy} className="btn-quiet px-3 py-2 text-xs">
                        <RefreshCw size={13} aria-hidden="true" /> Actualiser
                    </button>
                </div>
            </header>

            {/* Filtres : un seul choix d'affichage (état ou verdict), plus la source. */}
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1.3fr)]">
                <fieldset className="min-w-0 sm:col-span-2 xl:col-span-1">
                    <legend className="readout mb-2">Afficher</legend>
                    <SegmentedControl size="sm" columns={4} options={STATE_OPTIONS} value={filter} onChange={setFilter} />
                </fieldset>
                <fieldset className="min-w-0">
                    <legend className="readout mb-2">Mon verdict</legend>
                    <SegmentedControl size="sm" columns={2} options={VERDICT_OPTIONS} value={filter} onChange={setFilter} />
                </fieldset>
                <fieldset className="min-w-0">
                    <legend className="readout mb-2">Source</legend>
                    <SegmentedControl size="sm" columns={3} options={SOURCE_OPTIONS} value={source} onChange={setSource} />
                </fieldset>
            </div>

            {error && (
                <p role="alert" className="text-sm text-danger flex items-start gap-2 break-words">
                    <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden="true" /> {error}
                </p>
            )}

            {pictures === null && (
                <div role="status" className="py-16 flex items-center justify-center gap-3 text-muted">
                    <Loader2 size={18} className="animate-spin" aria-hidden="true" />
                    <span className="text-sm">Chargement des images…</span>
                </div>
            )}

            {pictures && shown.length === 0 && !error && (
                <div className="tray p-8 text-center">
                    <Images size={28} className="mx-auto mb-3 text-muted" aria-hidden="true" />
                    <p className="text-sm text-ink2">Aucune image ici.</p>
                    <p className="text-sm text-muted mt-1">Elles apparaissent après un job (et après un banc dessin).</p>
                </div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-5 gap-y-5">
                {shown.map((p, i, list) => {
                    const d = draftOf(p);
                    const heading = i === 0 || list[i - 1].group !== p.group;
                    const dirty = p.feedback
                        ? d.verdict !== p.feedback.verdict || d.why !== p.feedback.why || d.change !== p.feedback.change
                        : !!(d.verdict || d.why || d.change);
                    const working = busy === p.id;
                    return (
                        <React.Fragment key={p.id}>
                            {heading && (
                                <h3 className={`lg:col-span-2 font-display text-lg text-ink pb-2 border-b border-rule break-words ${i === 0 ? '' : 'mt-4'}`}>{p.group}</h3>
                            )}
                            <article className={`card p-4 space-y-3 min-w-0 ${p.status === 'kept' ? '' : 'border-danger/50'}`}>
                                <div className="relative">
                                    <button
                                        type="button"
                                        onClick={() => setZoom(p)}
                                        aria-label="Agrandir l’image"
                                        className="block w-full rounded-input overflow-hidden bg-black border border-rule2 hover:border-ink transition-colors cursor-zoom-in"
                                    >
                                        <img
                                            src={getApiUrl(`/api/broll/gallery/image?id=${encodeURIComponent(p.id)}`)}
                                            alt={p.idea || p.said}
                                            loading="lazy"
                                            className={`w-full ${p.layout === 'hero' ? 'max-h-96 object-contain' : 'object-cover aspect-video'} ${p.status === 'kept' ? '' : 'opacity-70'}`}
                                        />
                                    </button>
                                    <span className={`absolute top-2 left-2 pointer-events-none ${p.status === 'kept' ? 'badge-ink' : 'badge-danger'}`}>
                                        {p.status === 'kept' ? (p.layout === 'hero' ? 'Gardée · plein écran' : 'Gardée') : 'Refusée'}
                                    </span>
                                    <span className="absolute top-2 right-2 pointer-events-none w-7 h-7 rounded-input bg-paper/80 text-ink2 inline-flex items-center justify-center" aria-hidden="true">
                                        <Maximize2 size={13} />
                                    </span>
                                </div>

                                <blockquote className="text-base text-ink leading-snug break-words">« {p.said} »</blockquote>
                                {p.idea && <p className="text-sm text-muted break-words"><span className="text-ink2">Idée :</span> {p.idea}</p>}
                                {p.why && <p className="text-sm text-danger break-words">Refusée : {p.why}</p>}

                                <div className="flex items-center gap-2" role="group" aria-label="Mon verdict">
                                    <button type="button" disabled={working} onClick={() => save(p, d.verdict === 'up' ? '' : 'up')}
                                        aria-pressed={d.verdict === 'up'} aria-label="J’aime cette image" title="J’aime"
                                        className={verdictBtn(d.verdict === 'up')}>
                                        <ThumbsUp size={16} aria-hidden="true" />
                                    </button>
                                    <button type="button" disabled={working} onClick={() => patch(p.id, { verdict: d.verdict === 'down' ? '' : 'down' })}
                                        aria-pressed={d.verdict === 'down'} aria-label="Je n’aime pas cette image" title="J’aime pas"
                                        className={verdictBtn(d.verdict === 'down')}>
                                        <ThumbsDown size={16} aria-hidden="true" />
                                    </button>
                                    <span className="text-xs text-muted inline-flex items-center gap-1.5 ml-1" aria-live="polite">
                                        {working && <><Loader2 size={14} className="animate-spin" aria-hidden="true" /> Enregistrement…</>}
                                        {saved === p.id && <><Check size={14} className="text-ink" aria-hidden="true" /> Enregistré</>}
                                    </span>
                                </div>

                                {(d.verdict || d.why || d.change) && (
                                    <div className="space-y-3">
                                        <label className="block">
                                            <span className="readout block mb-1">Pourquoi ?</span>
                                            <textarea rows={2} value={d.why} disabled={working}
                                                onChange={(e) => patch(p.id, { why: e.target.value })}
                                                className="input-field text-sm w-full py-2 px-2.5 resize-y" />
                                        </label>
                                        <label className="block">
                                            <span className="readout block mb-1">Ce que je veux changer dedans</span>
                                            <textarea rows={2} value={d.change} disabled={working}
                                                onChange={(e) => patch(p.id, { change: e.target.value })}
                                                className="input-field text-sm w-full py-2 px-2.5 resize-y" />
                                        </label>
                                        <button type="button" disabled={working || !dirty} onClick={() => save(p)}
                                            className="btn-primary px-4 py-2 text-xs">
                                            Enregistrer
                                        </button>
                                    </div>
                                )}

                                <details className="border-t border-rule pt-2">
                                    <summary className="cursor-pointer readout hover:text-ink py-1.5 [@media(pointer:coarse)]:py-3">Prompt et graine</summary>
                                    <p className="mt-2 font-mono text-xs leading-relaxed text-ink2 break-words">{p.prompt}</p>
                                    <p className="readout mt-2">Graine {p.seed ?? '—'} · {p.date}</p>
                                </details>
                            </article>
                        </React.Fragment>
                    );
                })}
            </div>

            {zoom && (
                <div
                    className="fixed inset-0 z-[100] bg-black flex items-center justify-center p-4 sm:p-10"
                    role="dialog"
                    aria-modal="true"
                    aria-label="Image agrandie"
                    onClick={() => setZoom(null)}
                >
                    <button
                        type="button"
                        autoFocus
                        className="absolute top-3 right-3 sm:top-5 sm:right-5 w-11 h-11 rounded-input border border-rule2 text-ink hover:border-ink inline-flex items-center justify-center transition-colors"
                        onClick={() => setZoom(null)}
                        aria-label="Fermer (Échap)"
                    >
                        <X size={22} aria-hidden="true" />
                    </button>
                    <figure className="max-h-full max-w-full min-h-0 flex flex-col items-center gap-3">
                        <img src={getApiUrl(`/api/broll/gallery/image?id=${encodeURIComponent(zoom.id)}`)} alt={zoom.idea || zoom.said}
                            className="max-h-[80vh] max-w-full object-contain rounded-input border border-rule2" />
                        <figcaption className="text-sm text-ink2 text-center max-w-2xl break-words">« {zoom.said} »</figcaption>
                    </figure>
                </div>
            )}
        </div>
    );
}
