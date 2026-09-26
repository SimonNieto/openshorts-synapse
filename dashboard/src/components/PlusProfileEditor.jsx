import React, { useEffect, useState } from 'react';
import { FlaskConical, Music, Film, Clock, User, Zap, Trash2, Copy, Image as ImageIcon, Loader2 } from 'lucide-react';
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
    return `${gem} · ${free}`;
};

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
export default function PlusProfileEditor({ isOpen, onClose, profile, music = [], accounts = [], geminiApiKey, onSave, onDelete, onDuplicate }) {
    const [p, setP] = useState(profile);
    const [history] = useState(loadNicheHistory);
    const [brollTest, setBrollTest] = useState(null); // null | 'running' | result
    const runBrollTest = async () => {
        setBrollTest('running');
        try {
            const headers = { 'Content-Type': 'application/json' };
            if (geminiApiKey) headers['X-Gemini-Key'] = geminiApiKey;
            setBrollTest(await apiJson('/api/plus/broll/test', {
                method: 'POST', headers, body: JSON.stringify({ style: p?.broll?.style || 'photo' }),
            }));
        } catch (e) {
            setBrollTest({ gemini: `error: ${e.message}`, free: '?' });
        }
    };
    useEffect(() => { setP(profile); }, [profile]);
    if (!isOpen || !p) return null;

    const set = (patch) => setP((cur) => ({ ...cur, ...patch }));
    const setIn = (key, patch) => setP((cur) => ({ ...cur, [key]: { ...(cur[key] || {}), ...patch } }));
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
                    <Toggle checked={p.clean_ending ?? true} onChange={(v) => set({ clean_ending: v })}
                        label="end on a full sentence" hint="Never stops mid-thought: cuts back to the last full stop (drops a dangling “cause…” after the punchline) or runs on to the next one, a few seconds at most." />
                </Section>

                <Section icon={<Film size={13} />} title="edit">
                    <div className="flex flex-wrap gap-1.5 mb-2">
                        {[['natural', 'clean: 2-3 plain words, calm reframes at sentence ends (like the big podcast channels)'], ['punchy', '1-2 big glowing words, zooms every 2-3 s'], ['clean', '2-4 words, softer zooms']].map(([v, hint]) => (
                            <button key={v} type="button" title={hint} onClick={() => set({ edit_style: v })} className={chip(p.edit_style === v)}>{v}</button>
                        ))}
                    </div>
                    <Toggle checked={p.fx?.smart_framing} onChange={(v) => setIn('fx', { smart_framing: v })}
                        label="smart framing" hint="Zooms centred on the face, tight on the hook and the strongest lines, wide elsewhere — measured, never random." />
                    <Toggle checked={p.fx?.look} onChange={(v) => setIn('fx', { look: v })}
                        label="sharp look" hint="Crisper detail, deeper contrast, a faint glow on highlights." />
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
                    <Toggle beta checked={p.broll?.enabled} onChange={(v) => setIn('broll', { enabled: v })}
                        label="images when something concrete is named"
                        hint="2-4 cutaways of 1.6 s per clip (never on the hook nor the punchline), exactly on the word — the kratom plant, a brain scan, soldiers. The AI picks the moments; clips become a real edit, not a re-upload." />
                    {p.broll?.enabled && (
                        <div className="mt-1 space-y-2">
                            <div className="flex flex-wrap items-center gap-1.5">
                                <span className="text-xs text-muted w-14">source</span>
                                {[['auto', 'auto', 'Gemini images, free photos for anything it cannot make (e.g. free tier).'],
                                    ['gemini', 'Gemini images', 'Generated in the chosen style. Billed per image on your Gemini key.'],
                                    ['free', 'free photos', 'Real photos from Wikimedia Commons (reusable licences only), credited in the description. Free.']].map(([v, label, hint]) => (
                                    <button key={v} type="button" title={hint} onClick={() => setIn('broll', { source: v })}
                                        className={chip((p.broll?.source || 'auto') === v)}>{label}</button>
                                ))}
                            </div>
                            <div className="flex flex-wrap items-center gap-1.5">
                                <span className="text-xs text-muted w-14">style</span>
                                {[['photo', 'documentary photo'], ['neon', 'neon science'], ['drawing', '2D drawing']].map(([v, label]) => (
                                    <button key={v} type="button" onClick={() => setIn('broll', { style: v })}
                                        className={chip((p.broll?.style || 'photo') === v)}>{label}</button>
                                ))}
                                <label className="flex items-center gap-1.5 text-xs text-muted ml-2">
                                    max
                                    <input type="number" min="1" max="4" value={p.broll?.max ?? 3}
                                        onChange={(e) => setIn('broll', { max: e.target.value })}
                                        className="input-field text-xs py-1 px-2 w-14" />
                                    per clip
                                </label>
                            </div>
                            <div className="flex flex-wrap items-center gap-2">
                                <button type="button" onClick={runBrollTest} disabled={brollTest === 'running'}
                                    className="btn-ghost px-3 py-1.5 text-xs inline-flex items-center gap-1.5">
                                    {brollTest === 'running' ? <Loader2 size={12} className="animate-spin" /> : <ImageIcon size={12} />}
                                    {brollTest === 'running' ? 'testing (~20 s)…' : 'test image sources'}
                                </button>
                                {brollTest && brollTest !== 'running' && (
                                    <span className="text-xs text-muted leading-relaxed">{brollVerdict(brollTest)}</span>
                                )}
                            </div>
                            <p className="text-[11px] text-muted">The style applies to Gemini images; free photos are real photos. The moments are picked with a small Gemini text call (free tier is enough).</p>
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
                    <Toggle beta checked={p.beta?.selection_v2} onChange={(v) => setIn('beta', { selection_v2: v })}
                        label="AI selection v2" hint="Opens exactly on the spoken hook sentence (never 'so, um…'), ends on the punchline, favours relatable / 'exposes' topics. The viral score is kept as is." />
                    <Toggle beta checked={p.beta?.series_titles} onChange={(v) => setIn('beta', { series_titles: v })}
                        label="series titles" hint="“Joe Rogan On …”, “… Exposes …!” + 1-2 emojis." />
                    {p.beta?.series_titles && (
                        <input value={p.beta?.series_name || ''} onChange={(e) => setIn('beta', { series_name: e.target.value })}
                            placeholder="speaker / series name, e.g. Joe Rogan" className="input-field text-sm mt-1" />
                    )}
                </Section>
            </div>
        </Modal>
    );
}
