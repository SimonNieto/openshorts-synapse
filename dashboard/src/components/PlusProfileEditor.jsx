import React, { useEffect, useId, useState } from 'react';
import { Clock, User, Zap, Trash2, Copy, Image as ImageIcon, Loader2, Brain, RefreshCw, ChevronDown, AlertTriangle, Video, Instagram, Youtube } from 'lucide-react';
import Modal from './ui/Modal';
import SegmentedControl from './ui/SegmentedControl';
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

// Quick-fill suggestions (recent niches): small rectangles, white fill when they match.
const chip = (active) => `px-3 py-1.5 [@media(pointer:coarse)]:min-h-[44px] rounded-input border text-xs transition-colors ${active
    ? 'border-ink bg-ink text-paper2'
    : 'border-rule2 bg-paper2 text-ink2 hover:border-ink hover:text-ink'}`;

function Toggle({ checked, onChange, label, hint, beta }) {
    const id = useId();
    return (
        <div className="flex items-start gap-3 py-1.5">
            <input id={id} type="checkbox" checked={!!checked} onChange={(e) => onChange(e.target.checked)}
                aria-describedby={hint ? `${id}-hint` : undefined}
                className="mt-0.5 w-4 h-4 shrink-0 accent-[var(--color-accent)] cursor-pointer" />
            <div className="min-w-0">
                <label htmlFor={id} className="text-sm text-ink cursor-pointer select-none">{label}</label>
                {beta && <span className="ml-2 readout px-1.5 py-0.5 rounded border border-rule2">Beta</span>}
                {hint && <p id={`${id}-hint`} className="text-xs text-muted leading-relaxed mt-0.5">{hint}</p>}
            </div>
        </div>
    );
}

// --- AI brain: who thinks at each step (plus.py BRAIN_PRESETS / ai_brain.STAGES) ---

const MODELS = [
    { v: 'gemini', label: 'Gemini', hint: 'Google Gemini Flash, billed per token on your key — cents per video. Uses none of your Claude plan.' },
    { v: 'haiku', label: 'Haiku', hint: 'Claude Haiku: fast and light, about a third of Sonnet on your plan.' },
    { v: 'sonnet', label: 'Sonnet', hint: 'Claude Sonnet: the default judge.' },
    { v: 'opus', label: 'Opus', hint: 'Claude Opus: the most careful, heaviest on your plan.' },
];
const STEPS = [
    { k: 'brief_score', label: 'Read & sort the video', hint: 'Reads the whole transcript once: who talks, the topic, and a score for every stretch. The biggest read of the job.', w: 30 },
    { k: 'detail', label: 'Pick & write the clips', hint: 'Chooses the clips from the shortlist and writes hooks, titles and descriptions. Where the quality shows.', w: 25 },
    { k: 'broll', label: 'B-roll plan', hint: 'Which moments get an image and what it shows (and the hook of a screen clip, in the same call).', w: 25 },
    { k: 'broll_art', label: 'B-roll art direction', hint: 'Writes the final prompt of every picture of a clip in the channel’s look, for the whole set at once (text only, no image).', w: 6 },
    { k: 'image_review', label: 'Check B-roll images', hint: 'Scores each image against its idea. On Gemini, the b-roll brain re-checks only the doubtful ones.', w: 8 },
    { k: 'layout', label: 'Framing', hint: 'A few frames of the source: face crop, screen or split screen.', w: 5 },
    { k: 'hook', label: 'Screen hook', hint: 'Rewrites the hook from the frames when the clip is a screen and no Claude b-roll did it.', w: 5 },
    { k: 'text', label: 'Editor text', hint: 'Later, in the clip editor: translate captions, regenerate a clip’s copy.', w: 2 },
];
const PRESETS = [
    { v: 'gemini', label: 'Gemini only', tag: 'No Claude', hint: 'No Claude at all. Nothing from your plan; Gemini bills a few cents per video.', claude: 0, gemini: 3 },
    { v: 'balanced', label: 'Balanced', tag: 'Default', hint: 'Gemini reads, Claude decides. The default.', claude: 2, gemini: 2 },
    { v: 'claude', label: 'Claude everywhere', tag: 'Light steps on Haiku', hint: 'Every step on Claude; the light ones on Haiku to spare the plan.', claude: 3, gemini: 0 },
    { v: 'claude_max', label: 'Claude max', tag: 'Heaviest', hint: 'Opus picks the clips and plans the b-roll. Best judgment, heaviest on the plan.', claude: 4, gemini: 0 },
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
    { v: 'light', label: 'Light', hint: 'Short thinking: fewest tokens.' },
    { v: 'normal', label: 'Normal', hint: 'Medium thinking.' },
    { v: 'deep', label: 'Deep', hint: 'Thinks longest before choosing: best picks, most tokens on these two steps.' },
    { v: 'max', label: 'Max', hint: 'Claude at its maximum effort: the most tokens of all.' },
];
const PLATFORM_OPTIONS = [
    { value: 'tiktok', label: 'TikTok', icon: <Video size={14} /> },
    { value: 'instagram', label: 'Instagram', icon: <Instagram size={14} /> },
    { value: 'youtube', label: 'YouTube', icon: <Youtube size={14} /> },
];

function ModelSwitch({ value, onChange, noGemini }) {
    return (
        <SegmentedControl size="sm" columns={4} value={value} onChange={onChange}
            options={MODELS.map((m) => ({ value: m.v, label: m.label, muted: m.v === 'gemini' && noGemini }))} />
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
    const activePreset = PRESETS.find((pr) => pr.v === preset);

    return (
        <div className="space-y-5">
            <div role="group" aria-labelledby="pp-brain-preset">
                <p id="pp-brain-preset" className="readout mb-2">Preset</p>
                <SegmentedControl columns={2} value={preset} onChange={pickPreset}
                    options={PRESETS.map((pr) => ({ value: pr.v, label: pr.label, hint: pr.tag }))} />
                <p className="text-xs text-muted leading-relaxed mt-2" aria-live="polite">
                    {activePreset ? activePreset.hint : 'Custom: each step is set by hand below.'}
                </p>
            </div>

            <div className="tray overflow-hidden">
                <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} aria-controls="pp-brain-steps"
                    className="w-full min-h-[44px] flex items-center justify-between gap-2 px-4 py-2.5 text-left hover:bg-paper2 transition-colors">
                    <span className="text-sm text-ink font-medium flex items-center gap-2">
                        Each step {preset === 'custom' && <span className="readout px-1.5 py-0.5 rounded border border-rule2">Custom</span>}
                    </span>
                    <span className="readout inline-flex items-center gap-1">
                        {open ? 'Hide' : 'Fine-tune'}
                        <ChevronDown size={13} className={`transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
                    </span>
                </button>
                {open && (
                    <div id="pp-brain-steps" className="border-t border-rule bg-paper2">
                        {/* The key: what each model costs, once, instead of a tooltip per button. */}
                        <dl className="px-4 py-3 grid sm:grid-cols-2 gap-x-6 gap-y-2 border-b border-rule">
                            {MODELS.map((m) => (
                                <div key={m.v} className="text-xs leading-snug">
                                    <dt className="inline text-ink font-medium">{m.label} </dt>
                                    <dd className="inline text-muted">
                                        {m.hint}{m.v === 'gemini' && noGemini ? ' (No Gemini key in Settings: Claude runs it instead.)' : ''}
                                    </dd>
                                </div>
                            ))}
                        </dl>
                        <ul className="divide-y divide-rule">
                            {STEPS.map((s) => (
                                <li key={s.k} role="group" aria-labelledby={`pp-step-${s.k}`}
                                    className="flex flex-col md:flex-row md:items-center gap-2 md:gap-4 px-4 py-3">
                                    <div className="min-w-0 flex-1">
                                        <p id={`pp-step-${s.k}`} className="text-sm text-ink">{s.label}</p>
                                        <p className="text-xs text-muted leading-snug mt-0.5">{s.hint}</p>
                                    </div>
                                    <div className="md:w-64 shrink-0">
                                        <ModelSwitch value={stages[s.k]} onChange={(v) => setStage(s.k, v)} noGemini={noGemini} />
                                    </div>
                                </li>
                            ))}
                        </ul>
                    </div>
                )}
            </div>

            <div className="space-y-3">
                <p className="readout">Claude thinking</p>
                {[['thinking', 'deep', 'Choosing the clips'],
                  ['thinking_broll', 'normal', 'B-roll images'],
                  ['thinking_art', b.thinking_broll || 'normal', 'B-roll art direction']].map(([key, dflt, label]) => (
                    <div key={key} role="group" aria-labelledby={`pp-${key}`}
                        className="grid gap-2 md:grid-cols-[minmax(0,1fr)_16rem] md:items-center">
                        <p id={`pp-${key}`} className="text-sm text-ink2">{label}</p>
                        <SegmentedControl size="sm" columns={4} value={b[key] || dflt} onChange={(v) => onChange({ [key]: v })}
                            options={THINKING_OPTS.map((t) => ({ value: t.v, label: t.label }))} />
                    </div>
                ))}
                <dl className="grid sm:grid-cols-2 gap-x-6 gap-y-1">
                    {THINKING_OPTS.map((t) => (
                        <div key={t.v} className="text-xs leading-snug">
                            <dt className="inline text-ink2">{t.label}: </dt>
                            <dd className="inline text-muted">{t.hint}</dd>
                        </div>
                    ))}
                </dl>
            </div>

            <div className="tray px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs">
                    <span className="text-ink2">
                        Claude {onClaude.length} step{onClaude.length === 1 ? '' : 's'}
                        <span className="text-muted"> · </span>
                        Gemini {onGemini}
                    </span>
                    <span className="readout">Claude plan ≈ {planUse}% of an all-Sonnet run</span>
                </div>
                <div className="h-1.5 mt-2.5 rounded-full bg-paper overflow-hidden" aria-hidden="true">
                    <div className="h-full rounded-full bg-ink2 transition-all" style={{ width: `${Math.min(100, Math.max(planUse, 2))}%` }} />
                </div>
                {noGemini && onGemini > 0 && (
                    <p className="text-xs text-warn mt-2.5 flex items-start gap-1.5">
                        <AlertTriangle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
                        No Gemini key in Settings: the Gemini steps will run on Claude instead.
                    </p>
                )}
            </div>

            <Toggle checked={b.fresh} onChange={(v) => onChange({ fresh: v })}
                label={<span className="inline-flex items-center gap-1.5"><RefreshCw size={13} className="text-muted" aria-hidden="true" /> Fresh picks on the next run</span>}
                hint="A video run before normally reuses the AI's earlier answers for free (same clips). Tick this to get new picks on your next run; it switches itself off afterwards." />
        </div>
    );
}

function Section({ id, icon, title, lede, children }) {
    return (
        <section aria-labelledby={id} className="pt-6 border-t border-rule">
            <div className="mb-4">
                <h3 id={id} className="font-display text-base text-ink flex items-center gap-2">
                    <span className="text-muted" aria-hidden="true">{icon}</span> {title}
                </h3>
                {lede && <p className="text-xs text-muted mt-1">{lede}</p>}
            </div>
            {children}
        </section>
    );
}

/**
 * Edit one Synapse Cut profile: everything a run of that channel needs.
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
            eyebrow="Channel profile"
            title={p.id ? 'Edit profile' : 'New profile'}
            size="lg"
            footer={(
                <div className="flex flex-col-reverse sm:flex-row sm:items-center sm:justify-between gap-3">
                    <div className="flex flex-wrap gap-2">
                        {p.id && onDuplicate && (
                            <button type="button" onClick={() => onDuplicate(p)} className="btn-ghost px-3 py-2 text-xs"><Copy size={13} aria-hidden="true" /> Duplicate</button>
                        )}
                        {p.id && onDelete && (
                            <button type="button" onClick={() => onDelete(p)} className="btn-danger px-3 py-2 text-xs"><Trash2 size={13} aria-hidden="true" /> Delete</button>
                        )}
                    </div>
                    <div className="flex gap-2">
                        <button type="button" onClick={onClose} className="btn-ghost px-4 py-2 text-sm flex-1 sm:flex-none">Cancel</button>
                        <button type="button" onClick={() => onSave(p)} className="btn-accent px-5 py-2 text-sm flex-1 sm:flex-none">Save profile</button>
                    </div>
                </div>
            )}
        >
            <div className="space-y-6">
                <div>
                    <label htmlFor="pp-name" className="readout block mb-1.5">Profile name</label>
                    <input id="pp-name" value={p.name || ''} onChange={(e) => set({ name: e.target.value })}
                        placeholder="e.g. Joe Rogan · podcast" className="input-field" />
                </div>

                <Section id="pp-account" icon={<User size={15} />} title="Account & niche">
                    <div className="space-y-4">
                        {accounts.length > 0 && (
                            <div role="group" aria-labelledby="pp-account-label">
                                <p id="pp-account-label" className="readout mb-2">Upload-Post account</p>
                                <SegmentedControl size="sm" columns={Math.min(accounts.length, 2)} value={p.upload_profile}
                                    onChange={(a) => set({ upload_profile: a })}
                                    options={accounts.map((a) => ({ value: a, label: a }))} />
                            </div>
                        )}
                        <div>
                            <label htmlFor="pp-niche" className="readout block mb-1.5">Niche, for hashtags</label>
                            <input id="pp-niche" value={p.niche || ''} onChange={(e) => set({ niche: e.target.value })}
                                placeholder="e.g. Joe Rogan podcast clips" className="input-field" />
                            {history.length > 0 && (
                                <div className="mt-2.5">
                                    <p id="pp-niche-recent" className="text-xs text-muted mb-1.5">Recent niches</p>
                                    <div className="flex flex-wrap gap-1.5" role="group" aria-labelledby="pp-niche-recent">
                                        {history.map((n) => {
                                            const on = (p.niche || '').toLowerCase() === n.toLowerCase();
                                            return (
                                                <button key={n} type="button" aria-pressed={on} onClick={() => set({ niche: n })} className={chip(on)}>{n}</button>
                                            );
                                        })}
                                    </div>
                                </div>
                            )}
                        </div>
                        <div>
                            <label htmlFor="pp-watermark" className="readout block mb-1.5">Channel name under the captions</label>
                            <input id="pp-watermark" value={p.watermark || ''} onChange={(e) => set({ watermark: e.target.value })}
                                aria-describedby="pp-watermark-hint"
                                placeholder="e.g. @TheSynapseCut" className="input-field" />
                            <p id="pp-watermark-hint" className="text-xs text-muted mt-1">Leave blank for none.</p>
                        </div>
                    </div>
                </Section>

                <Section id="pp-clips" icon={<Clock size={15} />} title="Clips" lede="The reference channels' best shorts run 16-33 s.">
                    <div className="grid grid-cols-3 gap-3">
                        <div className="flex flex-col justify-end">
                            <label htmlFor="pp-min" className="text-xs text-muted">Shortest (s)</label>
                            <input id="pp-min" type="number" min="5" max="170" value={p.clip_min ?? 15} onChange={(e) => set({ clip_min: e.target.value })} className="input-field text-sm mt-1" />
                        </div>
                        <div className="flex flex-col justify-end">
                            <label htmlFor="pp-max" className="text-xs text-muted">Longest (s)</label>
                            <input id="pp-max" type="number" min="10" max="180" value={p.clip_max ?? 35} onChange={(e) => set({ clip_max: e.target.value })} className="input-field text-sm mt-1" />
                        </div>
                        <div className="flex flex-col justify-end">
                            <label htmlFor="pp-count" className="text-xs text-muted">Clips</label>
                            <input id="pp-count" type="number" min="1" max="15" value={p.target_clips ?? ''} onChange={(e) => set({ target_clips: e.target.value || null })}
                                aria-describedby="pp-count-hint" placeholder="AI" className="input-field text-sm mt-1" />
                        </div>
                    </div>
                    <p id="pp-count-hint" className="text-xs text-muted mt-1.5">Clips left blank: the AI decides how many.</p>

                    <fieldset className="mt-5">
                        <legend className="readout mb-2">Length to aim for</legend>
                        <div className="grid grid-cols-3 gap-3">
                            <div className="flex flex-col justify-end">
                                <label htmlFor="pp-aim-from" className="text-xs text-muted">From (s)</label>
                                <input id="pp-aim-from" type="number" min="5" max="180" value={p.selection?.clip_target?.[0] ?? ''}
                                    onChange={(e) => setTarget(0, e.target.value)} className="input-field text-sm mt-1" placeholder="25" />
                            </div>
                            <div className="flex flex-col justify-end">
                                <label htmlFor="pp-aim-to" className="text-xs text-muted">To (s)</label>
                                <input id="pp-aim-to" type="number" min="5" max="180" value={p.selection?.clip_target?.[1] ?? ''}
                                    onChange={(e) => setTarget(1, e.target.value)} className="input-field text-sm mt-1" placeholder="40" />
                            </div>
                            <div className="flex flex-col justify-end">
                                <label htmlFor="pp-min-clips" className="text-xs text-muted">At least (clips)</label>
                                <input id="pp-min-clips" type="number" min="1" max="15" value={p.selection?.min_clips ?? ''}
                                    onChange={(e) => setIn('selection', { min_clips: e.target.value || null })} className="input-field text-sm mt-1" placeholder="2" />
                            </div>
                        </div>
                        <div className="mt-2.5 flex flex-wrap items-start gap-x-4 gap-y-2">
                            <p className="text-xs text-muted leading-relaxed flex-1 min-w-[14rem]">
                                Recommended: aim for {REC.clip_target[0]}-{REC.clip_target[1]} s inside the min/max above (a longer clip is cut back to its payoff), at least {REC.min_clips} clips so an off-niche source is not padded.
                            </p>
                            {(p.selection?.clip_target?.[0] != REC.clip_target[0] || p.selection?.clip_target?.[1] != REC.clip_target[1] || p.selection?.min_clips != REC.min_clips) && (
                                <button type="button" onClick={() => setIn('selection', { clip_target: [...REC.clip_target], min_clips: REC.min_clips })}
                                    className="btn-quiet px-3 py-1.5 text-xs shrink-0">Use recommended</button>
                            )}
                        </div>
                    </fieldset>
                    <p className="text-xs text-muted leading-relaxed mt-4">Every clip ends on a full sentence: cut back to the last full stop (drops a dangling “cause…” after the punchline) or run on to the next one, a few seconds at most.</p>
                </Section>

                <Section id="pp-brain" icon={<Brain size={15} />} title="AI brain" lede="Who thinks at each step of a run.">
                    <BrainSection brain={p.brain} presets={brainPresets} noGemini={!geminiApiKey}
                        onChange={(patch) => setIn('brain', patch)} />
                </Section>

                <Section id="pp-broll" icon={<ImageIcon size={15} />} title="B-roll images">
                    <Toggle checked={p.broll?.enabled} onChange={(v) => setIn('broll', { enabled: v })}
                        label="Images when something concrete is named"
                        hint="Images cut in when the speaker names something concrete, chosen and checked by the AI brain. Clear of the hook, the punchline and the last seconds." />
                    <p className="text-xs text-muted leading-relaxed mt-2">
                        One full-screen picture on the most visual moment and two or three wide cards above the head, made on this PC
                        (ComfyUI, Z-Image Turbo), planned and checked by the AI brain, in the documentary house look. Needs ComfyUI running:
                        a job without it stops when the images cannot be made.
                    </p>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 mt-3">
                        <button type="button" onClick={runBrollTest} disabled={brollTest === 'running'}
                            className="btn-ghost px-3 py-2 text-xs">
                            {brollTest === 'running' ? <Loader2 size={13} className="animate-spin" aria-hidden="true" /> : <ImageIcon size={13} aria-hidden="true" />}
                            {brollTest === 'running' ? 'Testing (up to ~1 min)…' : 'Test Claude and the local GPU'}
                        </button>
                        <p className="text-xs text-muted leading-relaxed min-w-0 break-words" aria-live="polite">
                            {brollTest && brollTest !== 'running' ? brollVerdict(brollTest) : ''}
                        </p>
                    </div>
                </Section>

                <Section id="pp-publish" icon={<Zap size={15} />} title="Publish">
                    <Toggle checked={p.auto_publish?.enabled} onChange={(v) => setIn('auto_publish', { enabled: v })}
                        label="Publish the 3 best clips automatically" hint="Next free 8h · 12h · 20h slots of the account above." />
                    {p.auto_publish?.enabled && (
                        <div role="group" aria-labelledby="pp-platforms" className="mt-3 sm:pl-7">
                            <p id="pp-platforms" className="readout mb-2">Platforms</p>
                            <SegmentedControl multi size="sm" columns={3} options={PLATFORM_OPTIONS}
                                value={p.auto_publish?.platforms || []}
                                onChange={(next) => { if (next.length) setIn('auto_publish', { platforms: next }); }} />
                        </div>
                    )}
                </Section>

            </div>
        </Modal>
    );
}
