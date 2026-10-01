import React, { useEffect, useState } from 'react';
import { Clock, User, Zap, Trash2, Copy, Image as ImageIcon, Loader2, Brain, RefreshCw } from 'lucide-react';
import Modal from './ui/Modal';
import { loadNicheHistory } from '../lib/nicheHistory';
import { apiJson } from '../lib/api';

// What the B-roll test says, in words a user can act on.
const brollVerdict = (r) => {
    if (!r) return null;
    const l = r.local || '';
    const local = l.startsWith('ok') ? `local GPU: working ✓ ${l.slice(2).trim()}`
        : l === 'offline' ? 'local GPU: ComfyUI not running (start it in Pinokio)'
        : l ? `local GPU: failed (${l.replace(/^error: /, '').slice(0, 120)})` : '';
    const c = r.claude || '';
    const claude = c.startsWith('ok') ? `Claude: working ✓ ${c.slice(2).trim()}`
        : c === 'not set up' ? 'Claude: not set up (CLAUDE_CODE_OAUTH_TOKEN in .env)'
        : c ? `Claude: failed (${c.replace(/^error: /, '').slice(0, 120)})` : '';
    return [claude, local].filter(Boolean).join(' · ');
};

// What the clip-selection audit (30 sep 2026) recommends for the "aim for" band and the clip floor.
const REC = { clip_target: [25, 40], min_clips: 2 };

const chip = (active) => `readout px-2.5 py-1.5 rounded-full border transition-colors ${active
    ? 'bg-brass/20 text-brass border-brass/50'
    : 'bg-paper3 text-ink2 border-transparent hover:border-rule2'}`;

function Toggle({ checked, onChange, label, hint, beta }) {
    return (
        <label className="flex items-start gap-2.5 py-1.5 cursor-pointer select-none">
            <input type="checkbox" checked={!!checked} onChange={(e) => onChange(e.target.checked)}
                className="mt-0.5 w-4 h-4 shrink-0 accent-[var(--color-accent)] cursor-pointer" />
            <span className="min-w-0">
                <span className="text-sm text-ink">{label}</span>
                {beta && <span className="ml-2 readout px-1.5 py-0.5 rounded bg-brass/15 text-brass">beta</span>}
                {hint && <span className="block text-xs text-muted leading-relaxed mt-0.5">{hint}</span>}
            </span>
        </label>
    );
}

// --- AI brain: who thinks at each step (plus.py BRAIN_PRESETS / ai_brain.STAGES) ---

const GEMINI_COLOR = '#5b8def';
const CLAUDE_COLOR = '#d97757';
const MODELS = [
    { v: 'gemini', label: 'Gemini', color: GEMINI_COLOR, hint: 'Google Gemini Flash, billed per token on your key — cents per video. Uses none of your Claude plan.' },
    { v: 'haiku', label: 'Haiku', color: CLAUDE_COLOR, hint: 'Claude Haiku: fast and light, about a third of Sonnet on your plan.' },
    { v: 'sonnet', label: 'Sonnet', color: CLAUDE_COLOR, hint: 'Claude Sonnet: the default judge.' },
    { v: 'opus', label: 'Opus', color: CLAUDE_COLOR, hint: 'Claude Opus: the most careful, heaviest on your plan.' },
];
const STEPS = [
    { k: 'brief_score', label: 'read & sort the video', hint: 'Reads the whole transcript once: who talks, the topic, and a score for every stretch. The biggest read of the job.', w: 30 },
    { k: 'detail', label: 'pick & write the clips', hint: 'Chooses the clips from the shortlist and writes hooks, titles and descriptions. Where the quality shows.', w: 25 },
    { k: 'broll', label: 'b-roll plan', hint: 'Which moments get an image and what it shows (and the hook of a screen clip, in the same call).', w: 25 },
    { k: 'broll_art', label: 'b-roll art direction', hint: 'Writes the final prompt of every picture of a clip in the channel’s look, for the whole set at once (text only, no image).', w: 6 },
    { k: 'image_review', label: 'check b-roll images', hint: 'Scores each image against its idea. On Gemini, the b-roll brain re-checks only the doubtful ones.', w: 8 },
    { k: 'layout', label: 'framing', hint: 'A few frames of the source: face crop, screen or split screen.', w: 5 },
    { k: 'hook', label: 'screen hook', hint: 'Rewrites the hook from the frames when the clip is a screen and no Claude b-roll did it.', w: 5 },
    { k: 'text', label: 'editor text', hint: 'Later, in the clip editor: translate captions, regenerate a clip’s copy.', w: 2 },
];
const PRESETS = [
    { v: 'gemini', label: 'Gemini only', hint: 'No Claude at all. Nothing from your plan; Gemini bills a few cents per video.', claude: 0, gemini: 3 },
    { v: 'balanced', label: 'Balanced', hint: 'Gemini reads, Claude decides. The default.', claude: 2, gemini: 2 },
    { v: 'claude', label: 'Claude everywhere', hint: 'Every step on Claude; the light ones on Haiku to spare the plan.', claude: 3, gemini: 0 },
    { v: 'claude_max', label: 'Claude max', hint: 'Opus picks the clips and plans the b-roll. Best judgment, heaviest on the plan.', claude: 4, gemini: 0 },
];
// Fallback copy of plus.py's presets (the server sends the real ones).
const PRESET_STAGES = {
    gemini: Object.fromEntries(STEPS.map((s) => [s.k, 'gemini'])),
    balanced: { brief_score: 'gemini', detail: 'sonnet', layout: 'gemini', broll: 'sonnet', broll_art: 'sonnet', image_review: 'gemini', hook: 'sonnet', text: 'gemini' },
    claude: { brief_score: 'haiku', detail: 'sonnet', layout: 'haiku', broll: 'sonnet', broll_art: 'sonnet', image_review: 'haiku', hook: 'sonnet', text: 'haiku' },
    claude_max: { brief_score: 'sonnet', detail: 'opus', layout: 'haiku', broll: 'opus', broll_art: 'sonnet', image_review: 'sonnet', hook: 'sonnet', text: 'haiku' },
};
// Rough share of a Claude plan per model, Sonnet = 1 (list prices ratio).
const PLAN_WEIGHT = { gemini: 0, haiku: 1 / 3, sonnet: 1, opus: 5 / 3 };
const THINKING_OPTS = [
    { v: 'light', label: 'light', hint: 'Short thinking: fewest tokens.' },
    { v: 'normal', label: 'normal', hint: 'Medium thinking.' },
    { v: 'deep', label: 'deep', hint: 'Thinks longest before choosing: best picks, most tokens on these two steps.' },
];

function Dots({ n, max = 4, color }) {
    return (
        <span className="inline-flex gap-0.5 align-middle">
            {Array.from({ length: max }, (_, i) => (
                <span key={i} className="w-1.5 h-1.5 rounded-full" style={{ background: i < n ? color : 'var(--color-rule2, #8883)' }} />
            ))}
        </span>
    );
}

function ModelSwitch({ value, onChange, noGemini }) {
    return (
        <div className="inline-flex rounded-full bg-paper3 p-0.5 shrink-0" role="radiogroup">
            {MODELS.map((m) => {
                const on = value === m.v;
                return (
                    <button key={m.v} type="button" role="radio" aria-checked={on} title={m.hint + (m.v === 'gemini' && noGemini ? ' (No Gemini key in Settings: Claude runs it instead.)' : '')}
                        onClick={() => onChange(m.v)}
                        className={`readout px-2.5 py-1 rounded-full inline-flex items-center gap-1.5 transition-colors ${on ? 'bg-paper text-ink shadow-sm' : 'text-muted hover:text-ink'}`}>
                        <span className="w-1.5 h-1.5 rounded-full" style={{ background: m.color, opacity: on ? 1 : 0.45 }} />
                        {m.label}
                    </button>
                );
            })}
        </div>
    );
}

function BrainSection({ brain, presets, onChange, noGemini }) {
    const b = brain || {};
    const presetStages = presets || PRESET_STAGES;
    const stages = { ...presetStages.balanced, ...(b.stages || presetStages[b.preset] || {}) };
    const preset = b.preset || 'balanced';
    const [open, setOpen] = useState(preset === 'custom');
    const pickPreset = (v) => onChange({ preset: v, stages: { ...presetStages[v] } });
    const setStage = (k, v) => {
        const next = { ...stages, [k]: v };
        const match = Object.keys(presetStages).find((p) => STEPS.every((s) => presetStages[p][s.k] === next[s.k]));
        onChange({ preset: match || 'custom', stages: next });
    };
    const total = STEPS.reduce((a, s) => a + s.w, 0);
    const planUse = Math.round((STEPS.reduce((a, s) => a + s.w * PLAN_WEIGHT[stages[s.k]], 0) / total) * 100);
    const onClaude = STEPS.filter((s) => stages[s.k] !== 'gemini');
    const onGemini = STEPS.length - onClaude.length;

    return (
        <div className="space-y-3">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {PRESETS.map((pr) => {
                    const on = preset === pr.v;
                    return (
                        <button key={pr.v} type="button" onClick={() => pickPreset(pr.v)} title={pr.hint}
                            className={`text-left px-3 py-2.5 rounded-input border transition-colors ${on ? 'border-brass bg-brass/10' : 'border-rule hover:border-rule2 bg-paper'}`}>
                            <span className="block text-sm text-ink">{pr.label}{pr.v === 'balanced' && <span className="text-brass"> ★</span>}</span>
                            <span className="block text-[11px] text-muted leading-snug mt-0.5 min-h-[2.2em]">{pr.hint}</span>
                            <span className="grid grid-cols-[auto_1fr] items-center gap-x-2 gap-y-1 mt-2 readout text-muted">
                                <span>claude</span><Dots n={pr.claude} color={CLAUDE_COLOR} />
                                <span>gemini</span><Dots n={pr.gemini} max={3} color={GEMINI_COLOR} />
                            </span>
                        </button>
                    );
                })}
            </div>

            <div className="rounded-input border border-rule bg-paper">
                <button type="button" onClick={() => setOpen(!open)}
                    className="w-full flex items-center justify-between gap-2 px-3 py-2 text-left">
                    <span className="text-sm text-ink">
                        each step {preset === 'custom' && <span className="ml-1.5 readout px-1.5 py-0.5 rounded bg-brass/15 text-brass">custom</span>}
                    </span>
                    <span className="readout text-muted">{open ? 'hide' : 'fine-tune'}</span>
                </button>
                {open && (
                    <div className="border-t border-rule divide-y divide-rule">
                        {STEPS.map((s) => (
                            <div key={s.k} className="flex flex-col sm:flex-row sm:items-center gap-1.5 sm:gap-3 px-3 py-2">
                                <span className="min-w-0 flex-1">
                                    <span className="block text-sm text-ink">{s.label}</span>
                                    <span className="block text-[11px] text-muted leading-snug">{s.hint}</span>
                                </span>
                                <ModelSwitch value={stages[s.k]} onChange={(v) => setStage(s.k, v)} noGemini={noGemini} />
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {[['thinking', 'deep', 'claude thinking: choosing the clips'],
              ['thinking_broll', 'normal', 'claude thinking: b-roll images']].map(([key, dflt, label]) => (
                <div key={key} className="flex flex-wrap items-center gap-x-4 gap-y-2">
                    <span className="text-xs text-muted">{label}</span>
                    <div className="inline-flex rounded-full bg-paper3 p-0.5">
                        {THINKING_OPTS.map((t) => (
                            <button key={t.v} type="button" title={t.hint} onClick={() => onChange({ [key]: t.v })}
                                className={`readout px-2.5 py-1 rounded-full transition-colors ${(b[key] || dflt) === t.v ? 'bg-paper text-ink shadow-sm' : 'text-muted hover:text-ink'}`}>
                                {t.label}
                            </button>
                        ))}
                    </div>
                </div>
            ))}

            <div className="rounded-input bg-paper3 px-3 py-2.5">
                <div className="flex items-center justify-between gap-3 text-xs">
                    <span className="text-ink2">
                        <span className="inline-flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full" style={{ background: CLAUDE_COLOR }} />Claude {onClaude.length} step{onClaude.length === 1 ? '' : 's'}</span>
                        <span className="text-muted"> · </span>
                        <span className="inline-flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full" style={{ background: GEMINI_COLOR }} />Gemini {onGemini}</span>
                    </span>
                    <span className="readout text-muted">claude plan ≈ {planUse}% of an all-Sonnet run</span>
                </div>
                <div className="h-1.5 mt-2 rounded-full bg-paper overflow-hidden">
                    <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(100, Math.max(planUse, 2))}%`, background: CLAUDE_COLOR }} />
                </div>
                {noGemini && onGemini > 0 && (
                    <p className="text-[11px] text-warn mt-2">No Gemini key in Settings: the Gemini steps will run on Claude instead.</p>
                )}
            </div>

            <Toggle checked={b.fresh} onChange={(v) => onChange({ fresh: v })}
                label={<span className="inline-flex items-center gap-1.5"><RefreshCw size={12} /> fresh picks on the next run</span>}
                hint="A video run before normally reuses the AI's earlier answers for free (same clips). Tick this to get new picks on your next run; it switches itself off afterwards." />
        </div>
    );
}

function Section({ icon, title, children }) {
    return (
        <section className="pt-4 border-t border-rule first:border-t-0 first:pt-0">
            <p className="eyebrow mb-2 flex items-center gap-1.5">{icon} {title}</p>
            {children}
        </section>
    );
}

/**
 * Edit one Clip Generator++ profile: everything a run of that channel needs.
 * Beta switches change what the AI does and are clearly marked as such.
 */
export default function PlusProfileEditor({ isOpen, onClose, profile, accounts = [], geminiApiKey, brainPresets, onSave, onDelete, onDuplicate }) {
    const [p, setP] = useState(profile);
    const [history] = useState(loadNicheHistory);
    const [brollTest, setBrollTest] = useState(null); // null | 'running' | result
    const runBrollTest = async () => {
        setBrollTest('running');
        try {
            setBrollTest(await apiJson('/api/plus/broll/test', {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}),
            }));
        } catch (e) {
            setBrollTest({ local: `error: ${e.message}` });
        }
    };
    useEffect(() => { setP(profile); }, [profile]);
    if (!isOpen || !p) return null;

    const set = (patch) => setP((cur) => ({ ...cur, ...patch }));
    const setIn = (key, patch) => setP((cur) => ({ ...cur, [key]: { ...(cur[key] || {}), ...patch } }));
    // Length to AIM for (plus.py selection.clip_target): both bounds or nothing.
    const setTarget = (i, v) => setP((cur) => {
        const t = [...(cur.selection?.clip_target || ['', ''])];
        t[i] = v;
        return { ...cur, selection: { ...(cur.selection || {}), clip_target: t[0] !== '' && t[1] !== '' ? t : (t[0] === '' && t[1] === '' ? null : t) } };
    });
    return (
        <Modal
            isOpen={isOpen}
            onClose={onClose}
            eyebrow="CLIP GENERATOR++ · PROFILE"
            title={p.id ? 'edit profile' : 'new profile'}
            size="lg"
            footer={(
                <div className="flex flex-wrap gap-2 justify-between">
                    <div className="flex gap-2">
                        {p.id && onDuplicate && (
                            <button type="button" onClick={() => onDuplicate(p)} className="btn-ghost px-3 py-2 text-xs inline-flex items-center gap-1.5"><Copy size={13} /> duplicate</button>
                        )}
                        {p.id && onDelete && (
                            <button type="button" onClick={() => onDelete(p)} className="btn-ghost px-3 py-2 text-xs inline-flex items-center gap-1.5 text-danger"><Trash2 size={13} /> delete</button>
                        )}
                    </div>
                    <div className="flex gap-2">
                        <button type="button" onClick={onClose} className="btn-ghost px-4 py-2 text-sm">cancel</button>
                        <button type="button" onClick={() => onSave(p)} className="btn-primary px-4 py-2 text-sm">save profile</button>
                    </div>
                </div>
            )}
        >
            <div className="space-y-4">
                <label className="block">
                    <span className="eyebrow">name</span>
                    <input value={p.name || ''} onChange={(e) => set({ name: e.target.value })}
                        placeholder="e.g. Joe Rogan · podcast" className="input-field text-sm mt-1" />
                </label>

                <Section icon={<User size={13} />} title="account & niche">
                    {accounts.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 mb-2">
                            {accounts.map((a) => (
                                <button key={a} type="button" onClick={() => set({ upload_profile: a })} className={chip(p.upload_profile === a)}>{a}</button>
                            ))}
                        </div>
                    )}
                    <input value={p.niche || ''} onChange={(e) => set({ niche: e.target.value })}
                        placeholder="niche for hashtags, e.g. Joe Rogan podcast clips" className="input-field text-sm" />
                    {history.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 mt-2">
                            {history.map((n) => (
                                <button key={n} type="button" onClick={() => set({ niche: n })} className={chip((p.niche || '').toLowerCase() === n.toLowerCase())}>{n}</button>
                            ))}
                        </div>
                    )}
                    <label className="block mt-2">
                        <span className="text-xs text-muted">channel name under the captions (blank = none)</span>
                        <input value={p.watermark || ''} onChange={(e) => set({ watermark: e.target.value })}
                            placeholder="e.g. @TheSynapseCut" className="input-field text-sm mt-1" />
                    </label>
                </Section>

                <Section icon={<Clock size={13} />} title="clips">
                    <div className="grid grid-cols-3 gap-2">
                        <label className="block"><span className="text-xs text-muted">min length (s)</span>
                            <input type="number" min="5" max="170" value={p.clip_min ?? 15} onChange={(e) => set({ clip_min: e.target.value })} className="input-field text-sm mt-1" /></label>
                        <label className="block"><span className="text-xs text-muted">max length (s)</span>
                            <input type="number" min="10" max="180" value={p.clip_max ?? 35} onChange={(e) => set({ clip_max: e.target.value })} className="input-field text-sm mt-1" /></label>
                        <label className="block"><span className="text-xs text-muted">clips (blank = AI)</span>
                            <input type="number" min="1" max="15" value={p.target_clips ?? ''} onChange={(e) => set({ target_clips: e.target.value || null })} className="input-field text-sm mt-1" /></label>
                    </div>
                    <p className="text-[11px] text-muted mt-1.5">The reference channels' best shorts run 16-33 s.</p>
                    <div className="grid grid-cols-3 gap-2 mt-2">
                        <label className="block"><span className="text-xs text-muted">aim for, from (s)</span>
                            <input type="number" min="5" max="180" value={p.selection?.clip_target?.[0] ?? ''}
                                onChange={(e) => setTarget(0, e.target.value)} className="input-field text-sm mt-1" placeholder="25" /></label>
                        <label className="block"><span className="text-xs text-muted">aim for, to (s)</span>
                            <input type="number" min="5" max="180" value={p.selection?.clip_target?.[1] ?? ''}
                                onChange={(e) => setTarget(1, e.target.value)} className="input-field text-sm mt-1" placeholder="40" /></label>
                        <label className="block"><span className="text-xs text-muted">at least (clips)</span>
                            <input type="number" min="1" max="15" value={p.selection?.min_clips ?? ''}
                                onChange={(e) => setIn('selection', { min_clips: e.target.value || null })} className="input-field text-sm mt-1" placeholder="2" /></label>
                    </div>
                    <p className="text-[11px] text-muted mt-1.5 flex flex-wrap items-center gap-x-2">
                        <span>Recommended: aim for {REC.clip_target[0]}-{REC.clip_target[1]} s inside the min/max above (a longer clip is cut back to its payoff), at least {REC.min_clips} clips so an off-niche source is not padded.</span>
                        {(p.selection?.clip_target?.[0] != REC.clip_target[0] || p.selection?.clip_target?.[1] != REC.clip_target[1] || p.selection?.min_clips != REC.min_clips) && (
                            <button type="button" onClick={() => setIn('selection', { clip_target: [...REC.clip_target], min_clips: REC.min_clips })}
                                className="readout text-brass hover:underline">use recommended</button>
                        )}
                    </p>
                    <p className="text-[11px] text-muted mt-1.5">Every clip ends on a full sentence: cut back to the last full stop (drops a dangling “cause…” after the punchline) or run on to the next one, a few seconds at most.</p>
                </Section>

                <Section icon={<Brain size={13} />} title="ai brain — who thinks at each step">
                    <BrainSection brain={p.brain} presets={brainPresets} noGemini={!geminiApiKey}
                        onChange={(patch) => setIn('brain', patch)} />
                </Section>



                <Section icon={<ImageIcon size={13} />} title="b-roll images">
                    <Toggle checked={p.broll?.enabled} onChange={(v) => setIn('broll', { enabled: v })}
                        label="images when something concrete is named"
                        hint="Images cut in when the speaker names something concrete, chosen and checked by the AI brain. Clear of the hook, the punchline and the last seconds." />
                    <p className="text-[11px] text-muted mt-1.5">
                        One full-screen picture on the most visual moment and two or three wide cards above the head, made on this PC
                        (ComfyUI, Z-Image Turbo), planned and checked by the AI brain, in the documentary house look. Needs ComfyUI running:
                        a job without it stops when the images cannot be made.
                    </p>
                    <div className="flex flex-wrap items-center gap-2 mt-2">
                        <button type="button" onClick={runBrollTest} disabled={brollTest === 'running'}
                            className="btn-ghost px-3 py-1.5 text-xs inline-flex items-center gap-1.5">
                            {brollTest === 'running' ? <Loader2 size={12} className="animate-spin" /> : <ImageIcon size={12} />}
                            {brollTest === 'running' ? 'testing (up to ~1 min)…' : 'test Claude and the local GPU'}
                        </button>
                        {brollTest && brollTest !== 'running' && (
                            <span className="text-xs text-muted leading-relaxed">{brollVerdict(brollTest)}</span>
                        )}
                    </div>
                </Section>

                <Section icon={<Zap size={13} />} title="publish">
                    <Toggle checked={p.auto_publish?.enabled} onChange={(v) => setIn('auto_publish', { enabled: v })}
                        label="publish the 3 best clips automatically" hint="Next free 8h · 12h · 20h slots of the account above." />
                    {p.auto_publish?.enabled && (
                        <div className="flex flex-wrap gap-1.5 mt-1">
                            {['tiktok', 'instagram', 'youtube'].map((pl) => {
                                const on = (p.auto_publish?.platforms || []).includes(pl);
                                return (
                                    <button key={pl} type="button" className={chip(on)} onClick={() => {
                                        const cur = p.auto_publish?.platforms || [];
                                        const next = on ? cur.filter((x) => x !== pl) : [...cur, pl];
                                        if (next.length) setIn('auto_publish', { platforms: next });
                                    }}>{pl}</button>
                                );
                            })}
                        </div>
                    )}
                </Section>

            </div>
        </Modal>
    );
}
