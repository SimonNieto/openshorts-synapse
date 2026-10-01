import React, { useState, useEffect, useCallback } from 'react';
import { Loader2, RefreshCw, Trash2, Undo2, Library } from 'lucide-react';
import { getApiUrl } from '../config';
import { apiJson } from '../lib/api';

const MODEL_LABEL = { zimage: 'Z-Image Turbo (fast)', flux: 'FLUX schnell (heavier)' };
const LAYOUT_LABEL = { rise: 'small card', full: 'full frame', hero: 'hero', card: 'wide card' };

/**
 * The channel's kept pictures of glossary notions (Clip Generator++, broll.py's
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
        <div className="h-full overflow-y-auto p-4 sm:p-6 md:p-8 max-w-6xl mx-auto animate-fade">
            <p className="eyebrow mb-1.5">10 · NOTION PICTURES</p>
            <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
                <h1 className="font-display lowercase text-2xl text-ink">Notion pictures</h1>
                <button type="button" onClick={load} disabled={!!busy} className="btn-quiet px-3 py-1.5 text-xs inline-flex items-center gap-1.5">
                    <RefreshCw size={13} /> refresh
                </button>
            </div>
            <p className="text-muted text-sm mb-6 lowercase">
                A glossary notion keeps up to {variants} pictures in the channel’s look (different shots), shown in turn in every clip
                whose image is simply that notion; a clip makes the missing one. A picture made with an older look is not used any more:
                forget it, or edit its prompt and make it again here (in the current look).
            </p>

            {!comfy && (
                <p className="text-xs text-danger mb-4">ComfyUI does not answer: start it in Pinokio before regenerating a picture.</p>
            )}
            {error && <p className="text-xs text-danger mb-4">{error}</p>}

            {notions === null && (
                <div className="py-16 text-center text-muted"><Loader2 size={22} className="animate-spin mx-auto" /></div>
            )}

            {notions && notions.length === 0 && !error && (
                <div className="text-center py-20 text-muted">
                    <Library size={40} className="mx-auto mb-4" />
                    <p className="lowercase">No picture kept yet. They appear after a clip whose image is the plain picture of a glossary notion (B-roll with the Claude planner).</p>
                </div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {(notions || []).map((n, i, list) => {
                    const d = draftOf(n);
                    const working = busy === n.id;
                    const dirty = d.prompt !== n.prompt || d.engine !== n.made_with;
                    const heading = i === 0 || list[i - 1].term !== n.term;
                    return (
                        <React.Fragment key={n.id}>
                        {heading && <p className="eyebrow lg:col-span-2 mt-2">{n.term}</p>}
                        <div className="flex gap-3 p-3 rounded-input border border-rule">
                            <img
                                src={getApiUrl(`/api/plus/notions/${n.id}/image?v=${n.v}`)}
                                alt={n.term}
                                className={`rounded-input bg-paper3 object-cover shrink-0 ${n.layout === 'rise' ? 'w-32 h-32 sm:w-40 sm:h-40' : n.layout === 'card' ? 'w-40 h-24 sm:w-48 sm:h-28' : 'w-24 h-40 sm:w-28 sm:h-48'}`}
                            />
                            <div className="grow min-w-0 space-y-2">
                                <div>
                                    <p className="text-sm text-ink font-medium truncate" title={n.term}>{n.term}</p>
                                    <p className="text-[11px] text-muted">
                                        {n.style} · {LAYOUT_LABEL[n.layout] || n.layout} · variant {n.variant}/{variants}{n.shot ? ` · ${n.shot} shot` : ''}
                                        {` · shown ${n.uses || 0}×`} · made with {MODEL_LABEL[n.made_with] || n.made_with}
                                        {n.manual ? ' · redone by hand' : n.score ? ` · score ${n.score}/5` : ''}
                                        {n.saved ? ` · ${n.saved}` : ''}
                                        {n.current_look === false && <span className="text-danger"> · older look, not used</span>}
                                    </p>
                                    {n.engine !== n.made_with && (
                                        <p className="text-[11px] text-muted">used by profiles set to {MODEL_LABEL[n.engine] || n.engine}</p>
                                    )}
                                </div>
                                <textarea
                                    rows={4}
                                    value={d.prompt}
                                    onChange={(e) => patch(n.id, { prompt: e.target.value })}
                                    disabled={working}
                                    placeholder="what the picture shows — add what you want to see"
                                    className="input-field text-xs w-full py-1 px-2 resize-y"
                                />
                                <div className="flex flex-wrap items-center gap-2">
                                    <select
                                        value={d.engine}
                                        onChange={(e) => patch(n.id, { engine: e.target.value })}
                                        disabled={working}
                                        className="input-field text-xs py-1 px-2"
                                    >
                                        {engines.map((m) => <option key={m} value={m}>{MODEL_LABEL[m] || m}</option>)}
                                    </select>
                                    <button type="button" onClick={() => regen(n)} disabled={!!busy || !d.prompt.trim()}
                                        className="btn-primary px-3 py-1 text-xs inline-flex items-center gap-1.5">
                                        {working ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                                        {working ? busyText : dirty ? 'regen with these changes' : 'regen'}
                                    </button>
                                    {n.has_prev && (
                                        <button type="button" onClick={() => restore(n)} disabled={!!busy}
                                            className="btn-quiet px-2.5 py-1 text-xs inline-flex items-center gap-1.5">
                                            <Undo2 size={13} /> previous
                                        </button>
                                    )}
                                    <button type="button" onClick={() => remove(n)} disabled={!!busy}
                                        className="btn-quiet px-2.5 py-1 text-xs inline-flex items-center gap-1.5">
                                        <Trash2 size={13} /> forget
                                    </button>
                                </div>
                            </div>
                        </div>
                        </React.Fragment>
                    );
                })}
            </div>
        </div>
    );
}
