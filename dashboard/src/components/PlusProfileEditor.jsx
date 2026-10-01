import React, { useEffect, useState } from 'react';
import { FlaskConical, Music, Film, Clock, User, Zap, Trash2, Copy, Image as ImageIcon, Loader2, Brain, RefreshCw } from 'lucide-react';
import Modal from './ui/Modal';
import { loadNicheHistory } from '../lib/nicheHistory';
import { apiJson } from '../lib/api';

// What the B-roll test says, in words a user can act on.
const brollVerdict = (r) => {
    if (!r) return null;
    const g = r.gemini || '';
    const gem = g === 'ok' ? 'Gemini images: working on your key ✓'
        : g === 'no key' ? 'Gemini images: no Gemini key set in Settings'
        : g.startsWith('billing') ? 'Gemini images: refused on your key (free tier / billing off) — "auto" will use free photos instead'
        : `Gemini images: failed (${g.replace(/^error: /, '').slice(0, 120)})`;
    const free = r.free === 'ok' ? 'free photos: working ✓' : `free photos: ${r.free}`;
    const l = r.local || '';
    const local = l.startsWith('ok') ? `local GPU: working ✓ ${l.slice(2).trim()}`
        : l === 'offline' ? 'local GPU: ComfyUI not running (start it in Pinokio)'
        : l ? `local GPU: failed (${l.replace(/^error: /, '').slice(0, 120)})` : '';
    const c = r.claude || '';
    const claude = c.startsWith('ok') ? `Claude: working ✓ ${c.slice(2).trim()}`
        : c === 'not set up' ? 'Claude: not set up (CLAUDE_CODE_OAUTH_TOKEN in .env)'
        : c ? `Claude: failed (${c.replace(/^error: /, '').slice(0, 120)})` : '';
    return [claude, local, gem, free].filter(Boolean).join(' · ');
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
    balanced: { brief_score: 'gemini', detail: 'sonnet', layout: 'gemini', broll: 'sonnet', image_review: 'gemini', hook: 'sonnet', text: 'gemini' },
    claude: { brief_score: 'haiku', detail: 'sonnet', layout: 'haiku', broll: 'sonnet', image_review: 'haiku', hook: 'sonnet', text: 'haiku' },
    claude_max: { brief_score: 'sonnet', detail: 'opus', layout: 'haiku', broll: 'opus', image_review: 'sonnet', hook: 'sonnet', text: 'haiku' },
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
export default function PlusProfileEditor({ isOpen, onClose, profile, music = [], accounts = [], geminiApiKey, brainPresets, onSave, onDelete, onDuplicate }) {
    const [p, setP] = useState(profile);
    const [history] = useState(loadNicheHistory);
    const [brollTest, setBrollTest] = useState(null); // null | 'running' | result
    const runBrollTest = async () => {
        setBrollTest('running');
        try {
            const headers = { 'Content-Type': 'application/json' };
            if (geminiApiKey) headers['X-Gemini-Key'] = geminiApiKey;
            setBrollTest(await apiJson('/api/plus/broll/test', {
                method: 'POST', headers, body: JSON.stringify({ style: p?.broll?.style || 'photo', engine: p?.broll?.engine || 'zimage' }),
            }));
        } catch (e) {
            setBrollTest({ gemini: `error: ${e.message}`, free: '?' });
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
    const moods = music.length ? music : [];
    const mood = moods.find((m) => m.mood === p.music?.mood);

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
                        placeholder="e.g. Joe Rogan · punchy" className="input-field text-sm mt-1" />
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

                <Section icon={<Film size={13} />} title="edit">
                    <div className="flex flex-wrap gap-1.5 mb-2">
                        {[['natural', 'clean: 2-3 plain words, calm reframes at sentence ends (like the big podcast channels)'],
                            ['premium', 'the natural look set in Montserrat ExtraBold (72 px, the same footprint as natural\'s 64): the geometric extra-bold the big podcast channels caption in'],
                            ['punchy', '1-2 big glowing words, zooms every 2-3 s'], ['clean', '2-4 words, softer zooms']].map(([v, hint]) => (
                            <button key={v} type="button" title={hint} onClick={() => set({ edit_style: v })} className={chip(p.edit_style === v)}>{v}</button>
                        ))}
                    </div>
                    <Toggle beta checked={p.fx?.smooth_camera} onChange={(v) => setIn('fx', { smooth_camera: v })}
                        label="smooth camera" hint="The frame holds and only glides (eased, never more than once every ~2.5 s) when the speaker has really moved; zoom changes glide instead of jumping; shot changes dissolve over ~4 frames; reaction shots are fewer (max 2), a bit longer and fade in and out." />
                    <Toggle checked={p.fx?.look} onChange={(v) => setIn('fx', { look: v })}
                        label="sharp look" hint="Crisper detail, deeper contrast, a faint glow on highlights." />
                    <Toggle checked={p.fx?.hq_chain} onChange={(v) => setIn('fx', { hq_chain: v })}
                        label="HQ render chain" hint="Every layer before the captions (reactions, motion, B-roll, hook) is encoded near-lossless and only the delivered file compresses: no more blur and banding in the blacks after five re-encodes. About twice the render time of a clip and a bigger file." />
                    <Toggle checked={p.fx?.spotlight} onChange={(v) => setIn('fx', { spotlight: v })}
                        label="spotlight on punchlines" hint="On the 2-3 strongest lines the edges close in softly around the face for half a second. No flash." />
                    <Toggle checked={p.fx?.streaks} onChange={(v) => setIn('fx', { streaks: v })}
                        label="light line + motion blur on zoom-ins" hint="Subtle — try it on a test first." />
                    <Toggle beta checked={p.fx?.reactions} onChange={(v) => setIn('fx', { reactions: v })}
                        label="reaction shots" hint="Cuts to the other person listening for ~1 s right after a strong line, while the speaker keeps talking — like the big podcast channels. Only when the source films both people; never over a shot that already shows the listener." />
                    <div className="py-1.5">
                        <span className="text-sm text-ink">hook at the top</span>
                        <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
                            {[['bold', 'bold headline', 'Big condensed caps, 1-2 key words in yellow, one line when it fits; fades in and out.'],
                                ['classic', 'classic box', 'The white card of the classic Clip Generator.'],
                                ['none', 'none', 'No text: the spoken first line is the hook.']].map(([v, label, hint]) => (
                                <button key={v} type="button" title={hint} onClick={() => set({ hook_style: v })}
                                    className={chip((p.hook_style || (p.hook_box ? 'classic' : 'none')) === v)}>{label}</button>
                            ))}
                            {(p.hook_style || (p.hook_box ? 'classic' : 'none')) !== 'none' && (
                                <label className="flex items-center gap-1.5 text-xs text-muted ml-1">
                                    on screen
                                    <input type="number" min="2" max="10" value={p.hook_seconds ?? 4}
                                        onChange={(e) => set({ hook_seconds: e.target.value })}
                                        className="input-field text-xs py-1 px-2 w-14" />
                                    s
                                </label>
                            )}
                        </div>
                        <span className="block text-xs text-muted leading-relaxed mt-1">
                            The first 1.5 s decide the swipe: the bold headline reads at a glance, above the face and far from the captions.
                        </span>
                    </div>
                    <label className="block mt-2">
                        <span className="text-xs text-muted">channel name under the captions (blank = none)</span>
                        <input value={p.watermark || ''} onChange={(e) => set({ watermark: e.target.value })}
                            placeholder="e.g. ZERO LIMITS" className="input-field text-sm mt-1" />
                    </label>
                </Section>

                <Section icon={<Music size={13} />} title="music bed">
                    <Toggle checked={p.music?.enabled} onChange={(v) => setIn('music', { enabled: v })}
                        label="music under the voice" hint="Ducked while he talks, whole mix brought to ~-11 LUFS like the reference shorts." />
                    {p.music?.enabled && (
                        <div className="mt-1 space-y-2">
                            {moods.length === 0 && <p className="text-xs text-warn">No music found: put tracks in OpenShorts/music/ (one sub-folder per mood).</p>}
                            <div className="flex flex-wrap gap-1.5">
                                {moods.map((m) => (
                                    <button key={m.mood || 'root'} type="button" onClick={() => setIn('music', { mood: m.mood })} className={chip((p.music?.mood || '') === m.mood)}>
                                        {m.label} · {m.tracks.length}
                                    </button>
                                ))}
                            </div>
                            {mood && mood.tracks.length > 0 && <p className="text-[11px] text-muted truncate">{mood.tracks.join(' · ')}</p>}
                            <label className="flex items-center gap-3 text-xs text-muted">
                                volume
                                <input type="range" min="0.05" max="0.5" step="0.01" value={p.music?.volume ?? 0.22}
                                    onChange={(e) => setIn('music', { volume: Number(e.target.value) })} className="flex-1" />
                                <span className="readout w-10">{Math.round((p.music?.volume ?? 0.22) * 100)}%</span>
                            </label>
                        </div>
                    )}
                </Section>

                <Section icon={<ImageIcon size={13} />} title="b-roll images">
                    <Toggle checked={p.broll?.enabled} onChange={(v) => setIn('broll', { enabled: v })}
                        label="images when something concrete is named"
                        hint="Images cut in when the speaker names something concrete, chosen and checked by the AI brain. Clear of the hook, the punchline and the last seconds." />
                    {p.broll?.enabled && (
                        <div className="mt-1 space-y-2">
                            {(
                                <div className="flex flex-wrap items-center gap-1.5">
                                    <span className="text-xs text-muted w-14">model</span>
                                    {[['zimage', 'Z-Image Turbo (fast)', '~12 s per image on the RTX 3060 (~45 s for the first one of a job: model load). The default for clips.'],
                                        ['flux', 'FLUX schnell (quality)', '~25 s per image (~40 s for the first) and heavier on the GPU; for when the images matter most.']].map(([v, label, hint]) => (
                                        <button key={v} type="button" title={hint} onClick={() => setIn('broll', { engine: v })}
                                            className={chip((p.broll?.engine || 'zimage') === v)}>{label}</button>
                                    ))}
                                </div>
                            )}
                            <p className="text-xs text-muted">
                                <span className="w-14 inline-block">brain</span>
                                {(() => {
                                    const v = p.brain?.stages?.broll || 'sonnet';
                                    return v === 'gemini' ? 'Gemini' : `Claude ${v[0].toUpperCase()}${v.slice(1)}`;
                                })()} — set under “ai brain” above (b-roll plan).
                            </p>
                            <div className="flex flex-wrap items-center gap-1.5">
                                <span className="text-xs text-muted w-14">style</span>
                                {[['auto', 'auto (AI picks)', 'Per image: a real photo for things you can photograph, neon science for the invisible (neurons, molecules, hormones), a drawing for mechanisms, cinematic for drama, vintage for the past, 3D for a clean object, comic for humour, a diagram for a process.'],
                                    ['photo', 'documentary photo'], ['neon', 'neon science'], ['drawing', '2D drawing'],
                                    ['cinematic', 'cinematic', 'Dark, contrasted film still with grain: drama, danger, tension.'],
                                    ['vintage', 'vintage', 'Black and white or sepia archive photo: the past, historical scenes.'],
                                    ['3d', '3D render', 'Clean studio 3D render: an object, an organ or a machine.'],
                                    ['comic', 'comic', 'Comic-book illustration: humour, anecdotes, exaggeration.'],
                                    ['diagram', 'diagram', 'Simple shapes, icons and arrows: processes, flows, cause and effect (no text).']].map(([v, label, hint]) => (
                                    <button key={v} type="button" title={hint} onClick={() => setIn('broll', { style: v })}
                                        className={chip((p.broll?.style || 'photo') === v)}>{label}</button>
                                ))}
                            </div>
                            <div className="flex flex-wrap items-center gap-1.5">
                                <span className="text-xs text-muted w-14">review</span>
                                {[['auto', 'auto', 'The images are cut into the clip straight away.'],
                                    ['manual', 'manual', 'The images are prepared but not cut in: on each clip, open "check images" to remove, redo or move them, then cut them in.']].map(([v, label, hint]) => (
                                    <button key={v} type="button" title={hint} onClick={() => setIn('broll', { review: v })}
                                        className={chip((p.broll?.review || 'auto') === v)}>{label}</button>
                                ))}
                            </div>
                            <div className="flex flex-wrap items-center gap-1.5">
                                <span className="text-xs text-muted w-14">images</span>
                                {[['literal', 'literal', 'Shows exactly what is named: salvia = the plant, knife = a knife.'],
                                    ['mixed', 'mixed', 'Half literal, half the idea behind the words (a mechanism, a consequence, an analogy).'],
                                    ['concept', 'idea first', 'Shows what the sentence means; literal only when the word itself is the point.']].map(([v, label, hint]) => (
                                    <button key={v} type="button" title={hint} onClick={() => setIn('broll', { mode: v })}
                                        className={chip((p.broll?.mode || 'mixed') === v)}>{label}</button>
                                ))}
                            </div>
                            <div className="flex flex-wrap items-center gap-1.5">
                                <span className="text-xs text-muted w-14">amount</span>
                                {(() => {
                                    const base = Math.max(1, Math.min(10, Number(p.broll?.max) || 6));
                                    const mixed = p.broll?.layout === 'mixed';
                                    // mixed: a fixed pace (broll.MIXED_FEW / MIXED_MAX), the profile's max does not apply
                                    const counts = mixed ? { less: 3, normal: 4, more: 4 } : {
                                        less: Math.max(1, Math.floor(base * 0.6 + 0.5)),
                                        normal: base,
                                        more: Math.min(12, Math.max(base + 1, Math.floor(base * 1.5 + 0.5))),
                                    };
                                    const opts = [['less', 'fewer', mixed ? 'One hero and two cards, 4 s apart.' : 'Only the strongest moments, about one image every 8-10 s, at least 4.5 s apart.'],
                                        ['normal', 'normal', mixed ? 'One hero and three cards, 4 s apart.' : 'About one image every 4-6 s, at least 3 s apart.'],
                                        ['more', 'more', 'Every concrete mention, about one image every 3-4 s, at least 2.4 s apart. Images stay short so they can follow each other.']];
                                    return (mixed ? opts.slice(0, 2) : opts).map(([v, label, hint]) => (
                                        <button key={v} type="button" title={hint} onClick={() => setIn('broll', { density: v })}
                                            className={chip((p.broll?.density || 'normal') === v)}>{label} · up to {counts[v]}</button>
                                    ));
                                })()}
                            </div>
                            <Toggle checked={p.broll?.real_photos} onChange={(v) => setIn('broll', { real_photos: v })}
                                label="real photos for famous places & flags"
                                hint="A famous place, landmark, city, country or a flag (the CN Tower, the Eiffel Tower, the flag of France) is a real photo from Wikimedia Commons (CC0 / public domain / CC BY, the credit goes in the description). Everything else stays generated, and so does a place or flag with no good photo. Needs the Claude brain on the B-roll step." />
                            <div className="flex flex-wrap items-center gap-1.5">
                                <span className="text-xs text-muted w-14">show</span>
                                    {[['mixed', 'hero + wide cards', 'One full-screen picture on the most visual moment (2.5-3.5 s, slow push-in, crossfade) and 2-3 wide cards above the head, 4 s apart. The premium look.'],
                                    ['rise', 'small card (previous)', 'The previous drawing: a small square card under the captions, with the settings this profile saved for it.'],
                                    ['full', 'full screen (previous)', 'The previous drawing: tall images on the whole frame, 1.2-1.5 s.']].map(([v, label, hint]) => (
                                    <button key={v} type="button" title={hint} onClick={() => setIn('broll', { layout: v })}
                                        className={chip((p.broll?.layout || 'full') === v)}>{label}</button>
                                ))}
                            </div>
                            {p.broll?.layout === 'mixed' && (
                                <div className="space-y-2 p-2.5 rounded-input border border-rule">
                                    <div className="flex flex-wrap items-center gap-1.5">
                                        <span className="text-xs text-muted w-14">hero</span>
                                        {[['std', '896×1600 · ~16 s', 'The full-screen picture, made in 9:16 at 896x1600: about 16 s on an RTX 3060.'],
                                            ['high', '1024×1792 · ~23 s', 'Bigger (1024x1792, about 23 s): a touch sharper on a 1080p phone, slower.']].map(([v, label, hint]) => (
                                            <button key={v} type="button" title={hint} onClick={() => setIn('broll', { hero_res: v })}
                                                className={chip((p.broll?.hero_res || 'std') === v)}>{label}</button>
                                        ))}
                                    </div>
                                    <p className="text-xs text-muted">cards: wide 16:10 at 60 % of the width, above the head (the one free band of a podcast frame once the hook is gone), each from its word to the end of the sentence (2.2-3.5 s), fade in and out. Fixed, like the hero's 2.5-3.5 s and its slow push-in.</p>
                                    <Toggle checked={p.broll?.label} onChange={(v) => setIn('broll', { label: v })}
                                        label="a keyword on each card" hint="The image's subject in small capitals, bottom-left of the card." />
                                    <label className="flex flex-col gap-1 text-xs text-muted">
                                        house look — one sentence put in every image prompt, before the clip's own style sheet
                                        <textarea rows={2} maxLength={200} value={p.broll?.house_look || ''}
                                            onChange={(e) => setIn('broll', { house_look: e.target.value })}
                                            placeholder="cinematic documentary photograph, 35 mm lens, natural light, teal and amber grade, fine film grain, shallow depth of field"
                                            className="input-field text-xs w-full py-1 px-2 resize-none" />
                                    </label>
                                    <div className="flex flex-wrap items-center gap-1.5">
                                        <span className="text-xs text-muted w-14">grade</span>
                                        {[['off', 'none', 'The pictures as the model made them (the historical light contrast / colour touch-up).'],
                                            ['cinematic', 'cinematic', 'One film look on every picture when it is cut in: a touch less saturation, lifted blacks, warm highlights, cool shadows, fine grain.'],
                                            ['clean', 'clean', 'The same, barely there, no grain.']].map(([v, label, hint]) => (
                                            <button key={v} type="button" title={hint} onClick={() => setIn('broll', { grade: v })}
                                                className={chip((p.broll?.grade || 'off') === v)}>{label}</button>
                                        ))}
                                    </div>
                                    <Toggle checked={p.broll?.sfx} onChange={(v) => setIn('broll', { sfx: v })}
                                        label="a soft whoosh when the hero arrives" hint="Mixed under the voice at -18 dB (assets/sfx/whoosh_soft.wav); nothing on the cards." />
                                    <p className="text-[11px] text-muted">In this layout the "auto" style stays photographic (photo / cinematic, neon only for the microscopic); a style chosen above applies to every image instead. Drawing fixed: premium edge, no exit zoom; "fewer" = 3 images, "normal" = 4, 4 s apart, none in the hook's seconds nor in the last 2 s.</p>
                                </div>
                            )}
                            <div className="flex flex-wrap items-center gap-2">
                                <button type="button" onClick={runBrollTest} disabled={brollTest === 'running'}
                                    className="btn-ghost px-3 py-1.5 text-xs inline-flex items-center gap-1.5">
                                    {brollTest === 'running' ? <Loader2 size={12} className="animate-spin" /> : <ImageIcon size={12} />}
                                    {brollTest === 'running' ? 'testing (up to ~1 min)…' : 'test image sources'}
                                </button>
                                {brollTest && brollTest !== 'running' && (
                                    <span className="text-xs text-muted leading-relaxed">{brollVerdict(brollTest)}</span>
                                )}
                            </div>
                            <p className="text-[11px] text-muted">The style applies to generated images (local GPU, Gemini); free photos are real photos. The "brain" picks the moments and what each image shows.</p>
                        </div>
                    )}
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

                <Section icon={<FlaskConical size={13} />} title="beta — changes what the AI picks">
                    <Toggle beta checked={p.beta?.playbook} onChange={(v) => setIn('beta', { playbook: v })}
                        label="Synapse Cut playbook" hint="Question titles, never a name in the title (names go in the description's credit line), opens on the hook sentence, a question to the viewer in the description, one stats JSON per clip." />
                    {p.beta?.playbook && (
                        <input value={p.beta?.playbook_show || ''} onChange={(e) => setIn('beta', { playbook_show: e.target.value })}
                            placeholder="show name for the credit line (empty = from the file name)" className="input-field text-sm mt-1" />
                    )}
                </Section>
            </div>
        </Modal>
    );
}
