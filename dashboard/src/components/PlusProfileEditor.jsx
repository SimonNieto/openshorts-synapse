import React, { useEffect, useId, useState } from 'react';
import { Clock, User, Zap, Trash2, Copy, Image as ImageIcon, Loader2, RefreshCw, Video, Instagram, Youtube, Tags } from 'lucide-react';
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

// The clip formats (plus.py CLIP_FORMATS, sent by the server with the topics): their names on screen.
const FORMAT_LABEL = { short: 'Short', standard: 'Standard', long: 'Long' };

// Quick-fill suggestions (recent niches): small rectangles, white fill when they match.
const chip = (active) => `px-3 py-1.5 [@media(pointer:coarse)]:min-h-[44px] rounded-input border text-xs transition-colors ${active
    ? 'border-ink bg-ink text-paper2'
    : 'border-rule2 bg-paper2 text-ink2 hover:border-ink hover:text-ink'}`;
// A topic outside the channel's brain and mind niche (playbook.NICHE_CORE): ochre, with the word, ticked or not.
const offChip = (active) => `px-3 py-1.5 [@media(pointer:coarse)]:min-h-[44px] rounded-input border text-xs transition-colors inline-flex items-center gap-1.5 ${active
    ? 'border-warn bg-warn/20 text-warn'
    : 'border-warn/50 bg-paper2 text-warn/90 hover:border-warn hover:text-warn'}`;

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

const PLATFORM_OPTIONS = [
    { value: 'tiktok', label: 'TikTok', icon: <Video size={14} /> },
    { value: 'instagram', label: 'Instagram', icon: <Instagram size={14} /> },
    { value: 'youtube', label: 'YouTube', icon: <Youtube size={14} /> },
];

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
export default function PlusProfileEditor({ isOpen, onClose, profile, accounts = [], formats = {}, topics = [], onSave, onDelete, onDuplicate }) {
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
    const picked = p.selection?.niche_topics || [];
    const toggleTopic = (id) => setIn('selection', { niche_topics: picked.includes(id) ? picked.filter((t) => t !== id) : [...picked, id] });
    const fmt = formats[p.format || 'standard'];
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

                <Section id="pp-account" icon={<User size={15} />} title="Channel">
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
                            <label htmlFor="pp-show" className="readout block mb-1.5">Show</label>
                            <input id="pp-show" value={p.show || ''} onChange={(e) => set({ show: e.target.value })}
                                aria-describedby="pp-show-hint" placeholder="e.g. Joe Rogan Experience" className="input-field" />
                            <p id="pp-show-hint" className="text-xs text-muted mt-1">Picks the hashtags, and names the show at the top of each description when the episode's title doesn't.</p>
                            {history.length > 0 && (
                                <div className="mt-2.5">
                                    <p id="pp-show-recent" className="text-xs text-muted mb-1.5">Recent</p>
                                    <div className="flex flex-wrap gap-1.5" role="group" aria-labelledby="pp-show-recent">
                                        {history.map((n) => {
                                            const on = (p.show || '').toLowerCase() === n.toLowerCase();
                                            return (
                                                <button key={n} type="button" aria-pressed={on} onClick={() => set({ show: n })} className={chip(on)}>{n}</button>
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

                <Section id="pp-topics" icon={<Tags size={15} />} title="Topics" lede="What the channel is about. The AI looks for these first.">
                    <div className="flex flex-wrap gap-1.5" role="group" aria-labelledby="pp-topics">
                        {topics.map((t) => {
                            const on = picked.includes(t.id);
                            return (
                                <button key={t.id} type="button" aria-pressed={on} onClick={() => toggleTopic(t.id)}
                                    className={t.off ? offChip(on) : chip(on)} title={t.off ? 'Outside the brain and mind niche' : undefined}>
                                    {t.label}
                                    {t.off && <span className="text-[10px] uppercase tracking-wide opacity-80">off niche</span>}
                                </button>
                            );
                        })}
                    </div>
                    {picked.length > 0 ? (
                        <div role="group" aria-labelledby="pp-offtopic" className="mt-4">
                            <p id="pp-offtopic" className="readout mb-2">A clip outside these topics</p>
                            <SegmentedControl size="sm" columns={2} value={p.selection?.niche_only ? 'drop' : 'lower'}
                                onChange={(v) => setIn('selection', { niche_only: v === 'drop' })}
                                options={[{ value: 'drop', label: 'Dropped', hint: "Only the channel's topics" },
                                    { value: 'lower', label: 'Kept, ranked lower', hint: "When it's really strong" }]} />
                        </div>
                    ) : (
                        <p className="text-xs text-muted mt-2">None picked: every topic counts the same.</p>
                    )}
                    {topics.some((t) => t.off && picked.includes(t.id)) && (
                        <p className="text-xs text-warn mt-2">
                            Off-niche topics ticked: clips about them pass too, outside the brain and mind niche.
                        </p>
                    )}
                </Section>

                <Section id="pp-clips" icon={<Clock size={15} />} title="Clips" lede="The reference channels' best shorts run 16-33 s.">
                    <div role="group" aria-labelledby="pp-length">
                        <p id="pp-length" className="readout mb-2">Length</p>
                        <SegmentedControl columns={3} value={p.format || 'standard'} onChange={(v) => set({ format: v })}
                            options={Object.entries(formats).map(([k, f]) => ({
                                value: k, label: FORMAT_LABEL[k] || k,
                                hint: `${f.clip_target[0]}–${f.clip_target[1]} s${k === 'standard' ? ' · recommended' : ''}`,
                            }))} />
                        {fmt && (
                            <p className="text-xs text-muted leading-relaxed mt-2">
                                Aims for {fmt.clip_target[0]}–{fmt.clip_target[1]} s, never under {fmt.clip_min} s or over {fmt.clip_max} s. Every clip ends on a full sentence.
                            </p>
                        )}
                    </div>
                    {/* No count (plus.CLIP_FLOOR): the AI keeps every clip good enough to publish. */}
                    <div className="mt-5">
                        <p className="readout mb-1.5">Number of clips</p>
                        <p className="text-xs text-muted leading-relaxed">
                            No set number: the AI keeps every clip good enough to publish, at least one, more when the video has more good moments.
                        </p>
                    </div>
                    <div className="mt-3">
                        <Toggle checked={p.fresh} onChange={(v) => set({ fresh: v })}
                            label={<span className="inline-flex items-center gap-1.5"><RefreshCw size={13} className="text-muted" aria-hidden="true" /> Fresh picks on the next run</span>}
                            hint="A video run before normally reuses the AI's earlier answers for free (same clips). Tick this to get new picks on your next run; it switches itself off afterwards." />
                    </div>
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
