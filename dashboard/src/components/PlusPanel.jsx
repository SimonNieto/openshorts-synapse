import React, { useEffect, useMemo, useState } from 'react';
import { Plus, Pencil, BarChart3, Loader2, AlertCircle } from 'lucide-react';
import { apiFetch, apiJson } from '../lib/api';
import MediaInput from './MediaInput';
import PlusProfileEditor from './PlusProfileEditor';

const SELECTED_KEY = 'os_plus_profile';

// One-line recap of what a profile will do, under its name.
const recap = (p) => [
    `${p.clip_min}-${p.clip_max}s`,
    p.selection?.clip_target && `aim ${p.selection.clip_target[0]}-${p.selection.clip_target[1]}s`,
    p.broll?.enabled && 'B-roll',
    p.watermark && `“${p.watermark}”`,
    p.auto_publish?.enabled && 'auto-publish',
    ({ gemini: 'Gemini only', balanced: 'Gemini + Claude', claude: 'Claude everywhere', claude_max: 'Claude max', custom: 'custom brain' })[p.brain?.preset || 'balanced'],
    p.brain?.fresh && 'fresh picks',
].filter(Boolean).join(' · ');

function StatsTable({ title, rows }) {
    if (!rows?.length) return null;
    const max = Math.max(...rows.map((r) => r.avg_views), 1);
    return (
        <figure className="min-w-0">
            <figcaption className="readout mb-2">{title}</figcaption>
            <ul className="space-y-1.5">
                {rows.map((r) => (
                    <li key={r.key} className="grid grid-cols-[minmax(0,7rem)_1fr_auto] items-center gap-2.5 text-xs">
                        <span className="text-ink2 truncate" title={r.key}>{r.key}</span>
                        <span className="h-1.5 rounded-full bg-paper3 overflow-hidden" aria-hidden="true">
                            <span className="block h-full bg-ink2 rounded-full" style={{ width: `${(r.avg_views / max) * 100}%` }} />
                        </span>
                        <span className="font-mono text-[11px] text-ink2 text-right tabular-nums">
                            {r.avg_views.toLocaleString()} <span className="text-muted">· {r.posts}</span>
                        </span>
                    </li>
                ))}
            </ul>
        </figure>
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
        <section aria-labelledby="plus-stats-title" aria-busy={busy} className="card p-4 sm:p-6">
            <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
                <div className="min-w-0">
                    <h3 id="plus-stats-title" className="font-display text-lg text-ink flex items-center gap-2">
                        <BarChart3 size={16} className="text-muted" aria-hidden="true" /> What works on your channels
                    </h3>
                    <p className="readout mt-1">Last 60 days · from Upload-Post</p>
                </div>
                <button type="button" onClick={load} disabled={busy || !uploadPostKey || !accounts.length}
                    className="btn-quiet px-3 py-2 text-xs">
                    {busy && <Loader2 size={13} className="animate-spin" aria-hidden="true" />} {data ? 'Refresh' : 'Load my stats'}
                </button>
            </div>
            {!uploadPostKey && <p className="text-sm text-muted">Needs your Upload-Post key (Settings).</p>}
            {error && (
                <p role="alert" className="text-sm text-danger flex items-start gap-2 break-words">
                    <AlertCircle size={15} className="mt-0.5 shrink-0" aria-hidden="true" /> {error}
                </p>
            )}
            {data && data.total_posts === 0 && (
                <p className="text-sm text-muted">
                    No published short of yours found yet ({data.rows} posts read from Upload-Post, {data.unmatched} not made with Synapse AI).
                    Views appear a day or two after posting.
                </p>
            )}
            {data && data.total_posts > 0 && (
                <div className="space-y-6">
                    <p className="text-xs text-muted">Average views per short · number of shorts after the dot.</p>
                    <div className="grid md:grid-cols-2 gap-x-8 gap-y-6">
                        <StatsTable title="By profile" rows={g.profile} />
                        <StatsTable title="By length" rows={g.duration} />
                        <StatsTable title="By edit style" rows={g.edit_style} />
                        <StatsTable title="By posting hour" rows={g.hour} />
                        <StatsTable title="By AI viral score" rows={g.ai_score} />
                        <StatsTable title="By account" rows={g.account} />
                        <StatsTable title="By topic" rows={g.topic} />
                        <StatsTable title="By title shape" rows={g.title_form} />
                        <StatsTable title="Opens on its hook sentence" rows={g.hook_aligned} />
                    </div>
                    <div className="border-t border-rule pt-4">
                        <p className="readout mb-2">Your best shorts</p>
                        <ol className="space-y-1.5">
                            {data.posts.slice(0, 8).map((p) => (
                                <li key={p.key} className="flex items-center gap-3 text-xs">
                                    <span className="font-mono text-[11px] w-16 text-right tabular-nums text-ink shrink-0">{Math.round(p.views).toLocaleString()}</span>
                                    <span className="flex-1 min-w-0 truncate text-ink2" title={p.title}>{p.title}</span>
                                    <span className="font-mono text-[11px] text-muted shrink-0 hidden min-[420px]:inline">{[p.profile, p.duration && `${Math.round(p.duration)}s`].filter(Boolean).join(' · ')}</span>
                                </li>
                            ))}
                        </ol>
                    </div>
                </div>
            )}
        </section>
    );
}

/**
 * Synapse Cut (ex Clip Generator++): the classic generator, driven by a saved channel profile.
 * Nothing here touches the classic Clip Generator's own settings.
 */
export default function PlusPanel({ onProcess, isProcessing, publishProfiles = [], defaultProfile = '', canAutoPublish, uploadPostKey, geminiApiKey, onProfileChange }) {
    const [profiles, setProfiles] = useState(null);
    const [defaults, setDefaults] = useState(null);
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
        <div className="max-w-4xl mx-auto p-4 sm:p-8 space-y-8 animate-fade">
            <header className="border-b border-rule pb-6">
                <p className="eyebrow">Synapse Cut</p>
                <h2 className="page-title mt-2">Pick a profile, drop a video</h2>
                <p className="page-lede mt-2">
                    Each profile is a channel's full recipe: account, niche, lengths, AI brain, B-roll, publishing; the look itself is the house recipe. The classic Clip Generator stays untouched.
                </p>
            </header>

            {error && (
                <p role="alert" className="text-sm text-danger flex items-start gap-2 break-words">
                    <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden="true" /> {error}
                </p>
            )}

            {/* The channel profiles: one recipe card each; the selected one drives the run. */}
            <section aria-labelledby="plus-profiles-title" className="space-y-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h3 id="plus-profiles-title" className="font-display text-lg text-ink">Channel profiles</h3>
                    {profiles && <span className="readout">{profiles.length} profile{profiles.length === 1 ? '' : 's'}</span>}
                </div>
                {profiles === null && !error && (
                    <p role="status" className="flex items-center gap-2 text-sm text-muted">
                        <Loader2 size={15} className="animate-spin" aria-hidden="true" /> Loading the profiles…
                    </p>
                )}
                <ul className="grid sm:grid-cols-2 gap-3">
                    {(profiles || []).map((p) => {
                        const active = p.id === selectedId;
                        return (
                            <li key={p.id} className={`relative rounded-card border transition-colors ${active
                                ? 'border-vermilion bg-vermilionsoft'
                                : 'border-rule bg-paper2 hover:border-rule2'}`}>
                                <button type="button" onClick={() => setSelectedId(p.id)} aria-pressed={active}
                                    className="w-full min-h-[44px] text-left p-4 pr-14 rounded-card">
                                    <span className="flex items-center gap-2 min-w-0">
                                        <span className={`w-2 h-2 rounded-full shrink-0 ${active ? 'bg-vermilion' : 'border border-rule2'}`} aria-hidden="true" />
                                        <span className="text-sm font-medium text-ink truncate">{p.name}</span>
                                    </span>
                                    {p.upload_profile && <span className="block text-xs text-ink2 mt-1.5 truncate">{p.upload_profile}</span>}
                                    <span className="block font-mono text-[11px] leading-relaxed text-muted mt-1 line-clamp-2">{recap(p)}</span>
                                </button>
                                <button type="button" onClick={() => setEditing(p)} aria-label={`Edit profile ${p.name}`}
                                    className="absolute top-2.5 right-2.5 w-9 h-9 [@media(pointer:coarse)]:w-11 [@media(pointer:coarse)]:h-11 rounded-input text-muted hover:text-ink hover:bg-paper3 inline-flex items-center justify-center transition-colors">
                                    <Pencil size={15} aria-hidden="true" />
                                </button>
                            </li>
                        );
                    })}
                    <li>
                        <button type="button" onClick={newProfile}
                            className="w-full h-full min-h-[5.5rem] rounded-card border border-dashed border-rule2 text-sm text-muted hover:text-ink hover:border-ink inline-flex items-center justify-center gap-2 transition-colors">
                            <Plus size={16} aria-hidden="true" /> New profile
                        </button>
                    </li>
                </ul>
            </section>

            {profiles && !selected && (
                <p className="tray px-4 py-3 text-sm text-muted">{profiles.length ? 'Pick a profile above to start.' : 'Create your first profile to start.'}</p>
            )}

            {selected && (
                <section aria-labelledby="plus-drop-title" className="space-y-3">
                    <h3 id="plus-drop-title" className="font-display text-lg text-ink break-words">
                        Drop a video <span className="text-muted font-normal">· {selected.name}</span>
                    </h3>
                    <MediaInput
                        onProcess={onProcess}
                        isProcessing={isProcessing}
                        publishProfiles={publishProfiles}
                        defaultProfile={defaultProfile}
                        canAutoPublish={canAutoPublish}
                        plusProfile={selected}
                    />
                </section>
            )}

            <PlusStats uploadPostKey={uploadPostKey} accounts={accounts} />

            <PlusProfileEditor
                isOpen={!!editing}
                profile={editing}
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
