import React, { useState, useEffect, useCallback } from 'react';
import { Loader2, RefreshCw, Trash2, Undo2, AlertCircle, AlertTriangle } from 'lucide-react';
import { getApiUrl } from '../config';
import { apiJson } from '../lib/api';

const MODEL_LABEL = { zimage: 'Z-Image Turbo (fast)', flux: 'FLUX schnell (heavier)' };
const LAYOUT_LABEL = { rise: 'small card', full: 'full frame', hero: 'hero', card: 'wide card' };
// Status words are set lowercase by the handlers; the UI shows them in sentence case.
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

/**
 * The channel's kept pictures of glossary notions (Synapse Cut, broll.py's
 * notion memory). Every clip whose image is simply one of these notions shows
 * the picture kept here, unchanged. From this screen: see them, edit the prompt
 * and make one again (on Z-Image or FLUX) — the new one becomes the picture the
 * next clips use — put the previous one back, or forget one.
 */
export default function NotionLibrary() {
    const [notions, setNotions] = useState(null);
    const [engines, setEngines] = useState(['zimage', 'flux']);
    const [comfy, setComfy] = useState(true);
    const [variants, setVariants] = useState(2);
    const [drafts, setDrafts] = useState({});   // id -> { prompt, engine }
    const [busy, setBusy] = useState(null);     // id being made / restored / removed
    const [busyText, setBusyText] = useState('making…');
    const [error, setError] = useState('');

    const load = useCallback(async () => {
        setError('');
        try {
            const d = await apiJson('/api/plus/notions');
            setNotions(d.notions || []);
            if (d.engines?.length) setEngines(d.engines);
            if (d.variants) setVariants(d.variants);
            setComfy(!!d.comfy);
        } catch (e) {
            setError(e.detail || 'Could not load the pictures.');
            setNotions([]);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    // After a failed action the list may be out of date (a picture forgotten elsewhere): reload it, keep the message.
    const fail = async (e) => {
        const msg = e.detail || e.message;
        await load();
        setError(msg);
    };

    const replace = (n) => setNotions((list) => list.map((x) => (x.id === n.id ? n : x)));
    const draftOf = (n) => ({ prompt: n.prompt, engine: n.made_with, ...(drafts[n.id] || {}) });
    const patch = (id, changes) => setDrafts((d) => ({ ...d, [id]: { ...(d[id] || {}), ...changes } }));

    const regen = async (n) => {
        const d = draftOf(n);
        setBusyText('making…');
        setBusy(n.id);
        setError('');
        try {
            const r = await apiJson(`/api/plus/notions/${n.id}/regen`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompt: d.prompt, engine: d.engine }),
            });
            replace(r.notion);
            setDrafts((all) => { const { [n.id]: _gone, ...rest } = all; return rest; });
        } catch (e) {
            await fail(e);
        } finally {
            setBusy(null);
        }
    };

    const restore = async (n) => {
        setBusyText('restoring…');
        setBusy(n.id);
        setError('');
        try {
            const r = await apiJson(`/api/plus/notions/${n.id}/restore`, { method: 'POST' });
            replace(r.notion);
            setDrafts((all) => { const { [n.id]: _gone, ...rest } = all; return rest; });
        } catch (e) {
            await fail(e);
        } finally {
            setBusy(null);
        }
    };

    const remove = async (n) => {
        if (!window.confirm(`Forget the picture of "${n.term}"? The next clip that needs it will make a new one.`)) return;
        setBusyText('removing…');
        setBusy(n.id);
        setError('');
        try {
            await apiJson(`/api/plus/notions/${n.id}`, { method: 'DELETE' });
            setNotions((list) => list.filter((x) => x.id !== n.id));
        } catch (e) {
            await fail(e);
        } finally {
            setBusy(null);
        }
    };

    return (
        <div className="max-w-7xl mx-auto p-4 sm:p-8 space-y-8 animate-fade">
            <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between border-b border-rule pb-6">
                <div className="min-w-0">
                    <p className="eyebrow">Library</p>
                    <h2 className="page-title mt-2">Notion pictures</h2>
                    <p className="page-lede mt-2">
                        A glossary notion keeps up to {variants} pictures in the channel’s look (different shots), shown in turn in every clip
                        whose image is simply that notion; a clip makes the missing one. A picture made with an older look is not used any more:
                        forget it, or edit its prompt and make it again here (in the current look).
                    </p>
                </div>
                <button type="button" onClick={load} disabled={!!busy} className="btn-quiet px-3 py-2 text-xs shrink-0 self-start sm:self-auto">
                    <RefreshCw size={13} aria-hidden="true" /> Refresh
                </button>
            </header>

            {!comfy && (
                <p role="status" className="tray px-4 py-3 text-sm text-warn flex items-start gap-2">
                    <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
                    ComfyUI does not answer: start it in Pinokio before regenerating a picture.
                </p>
            )}
            {error && (
                <p role="alert" className="text-sm text-danger flex items-start gap-2 break-words">
                    <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden="true" /> {error}
                </p>
            )}

            {notions === null && (
                <div role="status" className="py-16 flex items-center justify-center gap-3 text-muted">
                    <Loader2 size={18} className="animate-spin" aria-hidden="true" />
                    <span className="text-sm">Loading the pictures…</span>
                </div>
            )}

            {notions && notions.length === 0 && !error && (
                <div className="tray p-5 sm:p-8 grid gap-6 sm:grid-cols-[minmax(0,15rem)_1fr] sm:items-center">
                    <figure className="w-full max-w-[15rem] mx-auto sm:mx-0">
                        <div className="aspect-[16/10] bg-black border border-rule2 rounded-card overflow-hidden">
                            <img src="/landing/fridge.jpg" alt="" loading="lazy" className="w-full h-full object-cover" />
                        </div>
                        <figcaption className="readout mt-2">Drawn B-roll · fridge</figcaption>
                    </figure>
                    <div>
                        <h3 className="font-display text-xl text-ink">No picture kept yet</h3>
                        <p className="text-sm text-muted mt-2 max-w-md leading-relaxed">
                            They appear after a clip whose image is the plain picture of a glossary notion (B-roll with the Claude planner).
                        </p>
                    </div>
                </div>
            )}

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-x-5 gap-y-4">
                {(notions || []).map((n, i, list) => {
                    const d = draftOf(n);
                    const working = busy === n.id;
                    const dirty = d.prompt !== n.prompt || d.engine !== n.made_with;
                    const heading = i === 0 || list[i - 1].term !== n.term;
                    const promptId = `notion-prompt-${n.id}`;
                    const engineId = `notion-engine-${n.id}`;
                    return (
                        <React.Fragment key={n.id}>
                        {heading && (
                            <h3 className={`xl:col-span-2 font-display text-lg text-ink pb-2 border-b border-rule break-words ${i === 0 ? '' : 'mt-6'}`}>{n.term}</h3>
                        )}
                        <article aria-label={`${n.term}, variant ${n.variant}`} className="card p-4 flex flex-col sm:flex-row gap-4">
                            <figure className="shrink-0 self-start">
                                <img
                                    src={getApiUrl(`/api/plus/notions/${n.id}/image?v=${n.v}`)}
                                    alt={n.term}
                                    className={`rounded-input bg-black border border-rule2 object-cover ${n.layout === 'rise' ? 'w-32 h-32 sm:w-40 sm:h-40' : n.layout === 'card' ? 'w-40 h-24 sm:w-48 sm:h-28' : 'w-24 h-40 sm:w-28 sm:h-48'}`}
                                />
                                <figcaption className="readout mt-1.5">Variant {n.variant}/{variants}</figcaption>
                            </figure>
                            <div className="grow min-w-0 space-y-3">
                                <div className="space-y-1.5">
                                    <p className="text-xs text-muted leading-relaxed">
                                        {n.style} · {LAYOUT_LABEL[n.layout] || n.layout}{n.shot ? ` · ${n.shot} shot` : ''}
                                        {` · shown ${n.uses || 0}×`} · made with {MODEL_LABEL[n.made_with] || n.made_with}
                                        {n.manual ? ' · redone by hand' : n.score ? ` · score ${n.score}/5` : ''}
                                        {n.saved ? ` · ${n.saved}` : ''}
                                    </p>
                                    {n.current_look === false && <span className="badge-danger">Older look · not used</span>}
                                    {n.engine !== n.made_with && (
                                        <p className="text-xs text-muted">Used by profiles set to {MODEL_LABEL[n.engine] || n.engine}</p>
                                    )}
                                </div>
                                <div>
                                    <label htmlFor={promptId} className="readout block mb-1">Prompt</label>
                                    <textarea
                                        id={promptId}
                                        rows={4}
                                        value={d.prompt}
                                        onChange={(e) => patch(n.id, { prompt: e.target.value })}
                                        disabled={working}
                                        placeholder="What the picture shows — add what you want to see"
                                        className="input-field text-xs w-full py-2 px-2.5 resize-y"
                                    />
                                </div>
                                <div className="flex flex-wrap items-end gap-2">
                                    <div className="min-w-0">
                                        <label htmlFor={engineId} className="readout block mb-1">Engine</label>
                                        <select
                                            id={engineId}
                                            value={d.engine}
                                            onChange={(e) => patch(n.id, { engine: e.target.value })}
                                            disabled={working}
                                            className="input-field text-xs py-2 px-2.5 w-auto max-w-full"
                                        >
                                            {engines.map((m) => <option key={m} value={m}>{MODEL_LABEL[m] || m}</option>)}
                                        </select>
                                    </div>
                                    <button type="button" onClick={() => regen(n)} disabled={!!busy || !d.prompt.trim()}
                                        className="btn-primary px-3 py-2 text-xs">
                                        {working ? <Loader2 size={13} className="animate-spin" aria-hidden="true" /> : <RefreshCw size={13} aria-hidden="true" />}
                                        {working ? cap(busyText) : dirty ? 'Regenerate with changes' : 'Regenerate'}
                                    </button>
                                    {n.has_prev && (
                                        <button type="button" onClick={() => restore(n)} disabled={!!busy}
                                            className="btn-quiet px-3 py-2 text-xs">
                                            <Undo2 size={13} aria-hidden="true" /> Previous
                                        </button>
                                    )}
                                    <button type="button" onClick={() => remove(n)} disabled={!!busy}
                                        className="btn-danger px-3 py-2 text-xs">
                                        <Trash2 size={13} aria-hidden="true" /> Forget
                                    </button>
                                </div>
                                <p className="sr-only" aria-live="polite">{working ? cap(busyText) : ''}</p>
                            </div>
                        </article>
                        </React.Fragment>
                    );
                })}
            </div>
        </div>
    );
}
