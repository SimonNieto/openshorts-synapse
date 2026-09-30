import React, { useEffect, useMemo, useState } from 'react';
import { Plus, Pencil, BarChart3, Loader2, Sparkles } from 'lucide-react';
import { apiFetch, apiJson } from '../lib/api';
import MediaInput from './MediaInput';
import PlusProfileEditor from './PlusProfileEditor';

const SELECTED_KEY = 'os_plus_profile';

const chip = (active) => `px-3 py-2 rounded-input border text-left transition-colors ${active
    ? 'border-brass bg-brass/10'
    : 'border-rule hover:border-rule2 bg-paper'}`;

// One-line recap of what a profile will do, under its name.
const recap = (p) => [
    p.edit_style,
    `${p.clip_min}-${p.clip_max}s`,
    p.fx?.smart_framing && 'smart zoom',
    p.fx?.look && 'sharp',
    p.fx?.spotlight && 'spotlight',
    p.fx?.streaks && 'light line',
    p.fx?.reactions && 'reactions',
    p.music?.enabled && 'music',
    p.broll?.enabled && 'b-roll',
    ({ bold: 'bold hook', classic: 'hook box', none: 'no hook' })[p.hook_style || (p.hook_box ? 'classic' : 'none')],
    p.clean_ending !== false && 'clean endings',
    p.watermark && `“${p.watermark}”`,
    p.auto_publish?.enabled && 'auto-publish',
    (p.beta?.selection_v2 || p.beta?.series_titles) && 'beta',
    ({ gemini: 'gemini only', balanced: 'gemini + claude', claude: 'claude everywhere', claude_max: 'claude max', custom: 'custom brain' })[p.brain?.preset || 'balanced'],
    p.brain?.fresh && 'fresh picks',
].filter(Boolean).join(' · ');

function StatsTable({ title, rows }) {
    if (!rows?.length) return null;
    const max = Math.max(...rows.map((r) => r.avg_views), 1);
    return (
        <div>
            <p className="eyebrow mb-1.5">{title}</p>
            <div className="space-y-1">
                {rows.map((r) => (
                    <div key={r.key} className="grid grid-cols-[7rem_1fr_4.5rem] items-center gap-2 text-xs">
                        <span className="text-ink2 truncate" title={r.key}>{r.key}</span>
                        <span className="h-2 rounded-full bg-paper3 overflow-hidden">
                            <span className="block h-full bg-brass rounded-full" style={{ width: `${(r.avg_views / max) * 100}%` }} />
                        </span>
                        <span className="readout text-right tabular-nums">{r.avg_views.toLocaleString()} <span className="text-muted">·{r.posts}</span></span>
                    </div>
                ))}
            </div>
        </div>
    );
}

function PlusStats({ uploadPostKey, accounts }) {
    const [data, setData] = useState(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const load = async () => {
        setBusy(true);
        setError('');
        try {
            const res = await apiFetch(`/api/plus/stats?days=60&users=${encodeURIComponent(accounts.join(','))}`, {
                headers: uploadPostKey ? { 'X-Upload-Post-Key': uploadPostKey } : {},
            });
            if (!res.ok) throw new Error((await res.text()).slice(0, 200));
            setData(await res.json());
        } catch (e) {
            setError(String(e.message || e));
        } finally {
            setBusy(false);
        }
    };
    const g = data?.groups || {};
    return (
        <section className="card p-5 mt-6">
            <div className="flex items-center justify-between gap-3 mb-3">
                <p className="text-sm text-ink font-medium lowercase flex items-center gap-2">
                    <BarChart3 size={15} className="text-brass" /> what works on your channels · last 60 days
                </p>
                <button type="button" onClick={load} disabled={busy || !uploadPostKey || !accounts.length}
                    className="btn-quiet px-3 py-1.5 text-xs inline-flex items-center gap-1.5">
                    {busy && <Loader2 size={13} className="animate-spin" />} {data ? 'refresh' : 'load my stats'}
                </button>
            </div>
            {!uploadPostKey && <p className="text-xs text-muted">Needs your Upload-Post key (Settings).</p>}
            {error && <p className="text-xs text-danger">{error}</p>}
            {data && data.total_posts === 0 && (
                <p className="text-xs text-muted">
                    No published short of yours found yet ({data.rows} posts read from Upload-Post, {data.unmatched} not made with OpenShorts).
                    Views appear a day or two after posting.
                </p>
            )}
            {data && data.total_posts > 0 && (
                <div className="space-y-5">
                    <p className="text-xs text-muted">Average views per short · number of shorts after the dot.</p>
                    <div className="grid md:grid-cols-2 gap-5">
                        <StatsTable title="by profile" rows={g.profile} />
                        <StatsTable title="by length" rows={g.duration} />
                        <StatsTable title="by edit style" rows={g.edit_style} />
                        <StatsTable title="by posting hour" rows={g.hour} />
                        <StatsTable title="by AI viral score" rows={g.ai_score} />
                        <StatsTable title="by account" rows={g.account} />
                        <StatsTable title="by topic" rows={g.topic} />
                        <StatsTable title="by title shape" rows={g.title_form} />
                        <StatsTable title="opens on its hook sentence" rows={g.hook_aligned} />
                    </div>
                    <div>
                        <p className="eyebrow mb-1.5">your best shorts</p>
                        <div className="space-y-1">
                            {data.posts.slice(0, 8).map((p) => (
                                <div key={p.key} className="flex items-center gap-3 text-xs">
                                    <span className="readout w-16 text-right tabular-nums text-brass">{Math.round(p.views).toLocaleString()}</span>
                                    <span className="flex-1 min-w-0 truncate text-ink2" title={p.title}>{p.title}</span>
                                    <span className="readout text-muted shrink-0">{[p.profile, p.duration && `${Math.round(p.duration)}s`].filter(Boolean).join(' · ')}</span>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            )}
        </section>
    );
}

/**
 * Clip Generator++: the classic generator, driven by a saved channel profile.
 * Nothing here touches the classic Clip Generator's own settings.
 */
export default function PlusPanel({ onProcess, isProcessing, publishProfiles = [], defaultProfile = '', canAutoPublish, uploadPostKey, geminiApiKey, onProfileChange }) {
    const [profiles, setProfiles] = useState(null);
    const [defaults, setDefaults] = useState(null);
    const [music, setMusic] = useState([]);
    const [brainPresets, setBrainPresets] = useState(null);
    const [selectedId, setSelectedId] = useState(() => { try { return localStorage.getItem(SELECTED_KEY) || ''; } catch { return ''; } });
    const [editing, setEditing] = useState(null);
    const [error, setError] = useState('');

    const accounts = useMemo(() => {
        const names = publishProfiles.map((p) => p.username).filter(Boolean);
        return names.length ? names : (defaultProfile ? [defaultProfile] : []);
    }, [publishProfiles, defaultProfile]);

    const load = async () => {
        try {
            const d = await apiJson('/api/plus/profiles');
            setProfiles(d.profiles || []);
            setDefaults(d.defaults);
            setMusic(d.music || []);
            setBrainPresets(d.brain_presets || null);
        } catch {
            setError('Could not load the profiles.');
        }
    };
    useEffect(() => { load(); }, []);

    const selected = (profiles || []).find((p) => p.id === selectedId) || null;
    useEffect(() => {
        try { localStorage.setItem(SELECTED_KEY, selectedId || ''); } catch { /* ignore */ }
        onProfileChange?.(selected);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [selectedId, profiles]);

    const save = async (p) => {
        setError('');
        try {
            const body = JSON.stringify(p);
            const saved = p.id
                ? await apiJson(`/api/plus/profiles/${p.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body })
                : await apiJson('/api/plus/profiles', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body });
            setEditing(null);
            await load();
            setSelectedId(saved.id);
        } catch (e) {
            setError(`Could not save: ${e.detail || e.message}`);
        }
    };
    const remove = async (p) => {
        try {
            await apiJson(`/api/plus/profiles/${p.id}`, { method: 'DELETE' });
            setEditing(null);
            if (selectedId === p.id) setSelectedId('');
            load();
        } catch (e) {
            setError(`Could not delete: ${e.detail || e.message}`);
        }
    };
    const newProfile = () => setEditing({ ...(defaults || {}), upload_profile: defaultProfile || accounts[0] || '', name: '' });

    return (
        <div className="max-w-3xl mx-auto p-4 sm:p-6 md:p-8 animate-fade">
            <p className="eyebrow mb-1.5 flex items-center gap-1.5"><Sparkles size={12} /> CLIP GENERATOR++</p>
            <h1 className="font-display lowercase text-2xl text-ink mb-2">pick a profile, drop a video</h1>
            <p className="text-muted text-sm mb-5 lowercase">
                Each profile is a channel's full recipe: account, length, edit, effects, music, publishing. The classic Clip Generator stays untouched.
            </p>
            {error && <p className="text-danger text-sm mb-3">{error}</p>}

            <div className="grid sm:grid-cols-2 gap-2 mb-5">
                {(profiles || []).map((p) => (
                    <div key={p.id} className={`${chip(p.id === selectedId)} flex items-start gap-2`}>
                        <button type="button" onClick={() => setSelectedId(p.id)} className="flex-1 min-w-0 text-left">
                            <span className="block text-sm text-ink truncate">{p.name}</span>
                            <span className="block readout normal-case text-muted truncate mt-0.5">{p.upload_profile && `${p.upload_profile} · `}{recap(p)}</span>
                        </button>
                        <button type="button" onClick={() => setEditing(p)} className="p-1 text-muted hover:text-ink shrink-0" aria-label="edit profile"><Pencil size={14} /></button>
                    </div>
                ))}
                <button type="button" onClick={newProfile} className="px-3 py-2 rounded-input border border-dashed border-rule2 text-sm text-muted hover:text-ink hover:border-brass inline-flex items-center gap-2 justify-center min-h-[3.25rem]">
                    <Plus size={15} /> new profile
                </button>
            </div>

            {profiles && !selected && (
                <p className="text-sm text-muted mb-4">{profiles.length ? 'Pick a profile above to start.' : 'Create your first profile to start.'}</p>
            )}

            {selected && (
                <MediaInput
                    onProcess={onProcess}
                    isProcessing={isProcessing}
                    publishProfiles={publishProfiles}
                    defaultProfile={defaultProfile}
                    canAutoPublish={canAutoPublish}
                    plusProfile={selected}
                />
            )}

            <PlusStats uploadPostKey={uploadPostKey} accounts={accounts} />

            <PlusProfileEditor
                isOpen={!!editing}
                profile={editing}
                music={music}
                accounts={accounts}
                geminiApiKey={geminiApiKey}
                brainPresets={brainPresets}
                onClose={() => setEditing(null)}
                onSave={save}
                onDelete={remove}
                onDuplicate={(p) => setEditing({ ...p, id: undefined, name: `${p.name} (copy)` })}
            />
        </div>
    );
}
