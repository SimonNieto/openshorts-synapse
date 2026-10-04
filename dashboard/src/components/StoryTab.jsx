import React, { useEffect, useRef, useState } from 'react';
import { Loader2, Lightbulb, Link2, ImagePlus, PenLine, Trash2, Plus, Clapperboard, ExternalLink, X, AlertTriangle, Check } from 'lucide-react';
import { apiFetch, apiJson } from '../lib/api';
import { getApiUrl } from '../config';
import JobProgressBar from './JobProgressBar';
import SegmentedControl from './ui/SegmentedControl';
import { loadSubtitleProfileStore, activeSubtitleProfileSettings } from './SubtitleModal';

// The draft survives leaving the tab (per-browser convenience only).
const DRAFT_KEY = 'os_story_draft_v1';
const loadDraft = () => { try { return JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null'); } catch { return null; } };
const saveDraft = (d) => { try { localStorage.setItem(DRAFT_KEY, JSON.stringify(d)); } catch { /* ignore */ } };

const EMOTIONS = ['neutral', 'shocked', 'explaining', 'happy', 'sad', 'confused', 'angry'];
const CAMERAS = ['zoom_in', 'zoom_out', 'pan_left', 'pan_right', 'static'];
const CAST = [{ id: 'casey', name: 'Casey' }, { id: 'prof', name: 'Prof. Margin' }];

// A toggle tag (cast in a scene): monochrome at rest, the signal edge + wash when on.
const chip = (active) => `inline-flex items-center justify-center px-2.5 py-1.5 min-h-[44px] sm:min-h-[32px] rounded-input border text-xs font-medium transition-colors ${active
    ? 'border-vermilion bg-vermilionsoft text-ink'
    : 'border-rule2 bg-paper2 text-ink2 hover:border-ink/50 hover:text-ink'}`;

const readError = async (res) => {
    const text = await res.text();
    try { return JSON.parse(text).detail || text; } catch { return text; }
};

// Same default caption profile the Clip Generator burns (SubtitleModal).
const captionStyle = () => {
    const s = activeSubtitleProfileSettings(loadSubtitleProfileStore());
    return JSON.stringify({
        position_percent: s.position, font_name: s.fontName, font_color: s.fontColor,
        highlight_color: s.highlightColor, border_color: s.borderColor, border_width: s.borderWidth,
        effect: s.effect, base_opacity: s.baseOpacity, uppercase: s.uppercase,
        font_size: s.fontSize, letter_spacing: s.letterSpacing, max_words: s.maxWords,
    });
};

/**
 * Story Channel: faceless 2D explainers with the recurring cast.
 * Inspiration (channel link / screenshot → ideas) → topic → script (edit
 * every scene) → narrated, animated, captioned video saved as a project.
 */
export default function StoryTab({ geminiApiKey, onOpenProject }) {
    const draft = loadDraft() || {};
    const [topic, setTopic] = useState(draft.topic || '');
    const [seconds, setSeconds] = useState(draft.seconds || 60);
    const [research, setResearch] = useState(draft.research ?? true);
    const [script, setScript] = useState(draft.script || null);
    const [voice, setVoice] = useState(draft.voice || 'am_michael');
    const [music, setMusic] = useState(draft.music ?? true);
    const [niche, setNiche] = useState(draft.niche || 'personal finance');
    const [config, setConfig] = useState(null);

    const [channelUrl, setChannelUrl] = useState('');
    const [hint, setHint] = useState('');
    const [shot, setShot] = useState(null); // data URL
    const [ideas, setIdeas] = useState(draft.ideas || null);
    const [ideasBusy, setIdeasBusy] = useState(false);

    const [writing, setWriting] = useState(false);
    const [job, setJob] = useState(null); // { id, status, progress, logs, result }
    const [error, setError] = useState('');
    const fileRef = useRef(null);

    const headers = geminiApiKey ? { 'X-Gemini-Key': geminiApiKey } : {};

    useEffect(() => { apiJson('/api/story/config').then(setConfig).catch(() => {}); }, []);
    useEffect(() => {
        saveDraft({ topic, seconds, research, script, voice, music, niche, ideas });
    }, [topic, seconds, research, script, voice, music, niche, ideas]);

    // Poll the render.
    useEffect(() => {
        if (!job?.id || job.status !== 'processing') return undefined;
        const t = setInterval(async () => {
            try {
                const d = await apiJson(`/api/story/status/${job.id}`);
                setJob((j) => ({ ...j, ...d, id: j.id }));
            } catch { /* keep polling */ }
        }, 1500);
        return () => clearInterval(t);
    }, [job?.id, job?.status]);

    const findIdeas = async (mode) => {
        setError('');
        setIdeasBusy(true);
        try {
            const res = await apiFetch('/api/story/ideas', {
                method: 'POST',
                headers: { ...headers, 'Content-Type': 'application/json' },
                body: JSON.stringify(mode === 'link'
                    ? { channel_url: channelUrl, hint }
                    : { image_base64: shot, hint }),
            });
            if (!res.ok) throw new Error(await readError(res));
            setIdeas(await res.json());
        } catch (e) {
            setError(String(e.message || e));
        } finally {
            setIdeasBusy(false);
        }
    };

    const pickShot = (file) => {
        if (!file) return;
        const reader = new FileReader();
        reader.onload = () => setShot(reader.result);
        reader.readAsDataURL(file);
    };

    const writeScript = async () => {
        if (!topic.trim()) return;
        setError('');
        setWriting(true);
        try {
            const res = await apiFetch('/api/story/script', {
                method: 'POST',
                headers: { ...headers, 'Content-Type': 'application/json' },
                body: JSON.stringify({ topic, seconds, research, cast: CAST.map((c) => c.id) }),
            });
            if (!res.ok) throw new Error(await readError(res));
            setScript(await res.json());
            setJob(null);
        } catch (e) {
            setError(String(e.message || e));
        } finally {
            setWriting(false);
        }
    };

    const setScene = (i, patch) => setScript((s) => ({ ...s, scenes: s.scenes.map((sc, k) => (k === i ? { ...sc, ...patch } : sc)) }));
    const removeScene = (i) => setScript((s) => ({ ...s, scenes: s.scenes.filter((_, k) => k !== i) }));
    const addScene = (i) => setScript((s) => {
        const scenes = [...s.scenes];
        scenes.splice(i + 1, 0, { narration: '', visual: '', characters: ['casey'], emotion: 'neutral', on_screen_text: '', camera: 'zoom_in' });
        return { ...s, scenes };
    });
    const toggleCast = (i, id) => {
        const cur = script.scenes[i].characters || [];
        const next = cur.includes(id) ? cur.filter((c) => c !== id) : [...cur, id];
        if (next.length) setScene(i, { characters: next });
    };

    const render = async () => {
        setError('');
        try {
            const res = await apiFetch('/api/story/render', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ script, voice, music, niche, caption_style: captionStyle() }),
            });
            if (!res.ok) throw new Error(await readError(res));
            const { job_id: id } = await res.json();
            setJob({ id, status: 'processing', progress: { percent: 0, stage: 'starting' }, logs: [] });
        } catch (e) {
            setError(String(e.message || e));
        }
    };

    const words = (script?.scenes || []).reduce((n, s) => n + (s.narration || '').split(/\s+/).filter(Boolean).length, 0);
    const rendering = job?.status === 'processing';


    return (
        <div className="max-w-5xl mx-auto px-4 py-6 sm:p-8 animate-fade">
            <header className="mb-8 sm:mb-10">
                <p className="eyebrow mb-2">Hidden economics</p>
                <h2 className="page-title">2D story videos</h2>
                <p className="page-lede mt-3">
                    Casey falls for the trap, Prof. Margin explains it. Start from an idea, edit the script scene by
                    scene, and get a narrated, animated, captioned short.
                </p>
            </header>

            {error && (
                <div role="alert" className="mb-6 px-3 py-2.5 rounded-input border border-danger/40 bg-danger/10 text-danger text-sm flex items-start gap-2">
                    <AlertTriangle size={16} className="shrink-0 mt-0.5" aria-hidden="true" /> <span className="break-words min-w-0">{error}</span>
                </div>
            )}

            <div className="space-y-6">
                {/* Inspiration */}
                <section aria-labelledby="story-inspiration-title" className="card p-4 sm:p-6">
                    <SectionHead id="story-inspiration-title" icon={<Lightbulb size={18} />} title="Inspiration">
                        Learn from a channel that works: give us its link or a screenshot, and get angles for your next video.
                    </SectionHead>

                    <div className="grid md:grid-cols-2 gap-4 md:gap-6">
                        <div className="min-w-0">
                            <label htmlFor="story-channel" className="block text-sm font-medium text-ink mb-1.5">Channel</label>
                            <div className="flex gap-2">
                                <input id="story-channel" value={channelUrl} onChange={(e) => setChannelUrl(e.target.value)}
                                    placeholder="@thepaintexplainer or channel link" className="input-field text-sm min-w-0" />
                                <button type="button" onClick={() => findIdeas('link')} disabled={ideasBusy || !channelUrl.trim()}
                                    className="btn-quiet px-3 text-xs shrink-0">
                                    <Link2 size={14} aria-hidden="true" /> Analyze
                                </button>
                            </div>
                        </div>
                        <div className="min-w-0">
                            <p id="story-shot-label" className="block text-sm font-medium text-ink mb-1.5">Or a screenshot of a channel</p>
                            <div className="flex gap-2 items-center">
                                <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={(e) => pickShot(e.target.files?.[0])} />
                                <button type="button" onClick={() => fileRef.current?.click()} aria-describedby="story-shot-label"
                                    className="btn-ghost px-3 py-2.5 text-xs min-w-0 flex-1 sm:flex-none">
                                    <ImagePlus size={14} aria-hidden="true" className="text-muted shrink-0" />
                                    <span className="truncate">{shot ? 'Screenshot ready' : 'Choose a screenshot'}</span>
                                </button>
                                {shot && (
                                    <>
                                        <button type="button" onClick={() => setShot(null)}
                                            className="w-11 h-11 sm:w-9 sm:h-9 shrink-0 rounded-input flex items-center justify-center text-muted hover:text-ink hover:bg-paper3 transition-colors"
                                            aria-label="Remove the screenshot">
                                            <X size={16} aria-hidden="true" />
                                        </button>
                                        <button type="button" onClick={() => findIdeas('shot')} disabled={ideasBusy}
                                            className="btn-quiet px-3 text-xs shrink-0">Analyze</button>
                                    </>
                                )}
                            </div>
                        </div>
                    </div>

                    <div className="mt-4">
                        <label htmlFor="story-hint" className="block text-sm font-medium text-ink mb-1.5">
                            Direction <span className="font-normal text-muted">(optional)</span>
                        </label>
                        <input id="story-hint" value={hint} onChange={(e) => setHint(e.target.value)}
                            placeholder="e.g. more about food and supermarkets" className="input-field text-sm" />
                    </div>

                    <div aria-live="polite">
                        {ideasBusy && (
                            <p className="text-sm text-muted mt-4 flex items-center gap-2">
                                <Loader2 size={14} className="animate-spin" aria-hidden="true" /> Reading the channel and finding angles…
                            </p>
                        )}
                    </div>

                    {ideas && !ideasBusy && (
                        <div className="mt-6 pt-5 border-t border-rule space-y-4">
                            {ideas.channel && <p className="readout normal-case">{ideas.channel}</p>}
                            {!!ideas.patterns?.length && (
                                <div>
                                    <h4 className="readout mb-2">What works there</h4>
                                    <ul className="text-sm text-ink2 space-y-1 list-disc pl-5 marker:text-muted">
                                        {ideas.patterns.map((p) => <li key={p}>{p}</li>)}
                                    </ul>
                                </div>
                            )}
                            {!!(ideas.ideas || []).length && (
                                <div>
                                    <h4 id="story-ideas-title" className="readout mb-2">Angles · pick one as your topic</h4>
                                    <div role="group" aria-labelledby="story-ideas-title" className="grid sm:grid-cols-2 gap-3">
                                        {(ideas.ideas || []).map((idea) => (
                                            <button key={idea.topic} type="button" onClick={() => setTopic(idea.topic)}
                                                aria-pressed={topic === idea.topic}
                                                className={`card card-hover relative text-left p-3.5 sm:p-4 ${topic === idea.topic ? 'border-vermilion bg-vermilionsoft' : ''}`}>
                                                <SelectMark active={topic === idea.topic} />
                                                <span className="block text-sm font-medium text-ink pr-8">{idea.topic}</span>
                                                <span className={`block text-xs mt-1 leading-relaxed ${topic === idea.topic ? 'text-ink2' : 'text-muted'}`}>{idea.angle}</span>
                                                <span className={`block text-xs mt-2 leading-relaxed ${topic === idea.topic ? 'text-ink2' : 'text-muted'}`}>
                                                    <span className="readout mr-1.5">Why</span>{idea.why}
                                                </span>
                                            </button>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                    )}
                </section>

                {/* Topic → script */}
                <section aria-labelledby="story-topic-title" className="card p-4 sm:p-6">
                    <SectionHead id="story-topic-title" icon={<PenLine size={18} />} title="Topic">
                        One question your video answers. Pick an angle above or write your own.
                    </SectionHead>
                    <textarea value={topic} onChange={(e) => setTopic(e.target.value)} rows={2} aria-labelledby="story-topic-title"
                        placeholder="e.g. Why gyms make more money when you never show up" className="input-field text-sm" />
                    <div className="flex flex-col sm:flex-row sm:flex-wrap sm:items-end gap-4 mt-4">
                        <div className="w-full sm:w-56">
                            <p id="story-length-title" className="readout mb-1.5">Length</p>
                            <div role="group" aria-labelledby="story-length-title">
                                <SegmentedControl
                                    size="sm"
                                    options={[45, 60, 75].map((s) => ({ value: s, label: `${s}s` }))}
                                    value={seconds}
                                    onChange={setSeconds}
                                />
                            </div>
                        </div>
                        <label className="flex items-center gap-2 text-sm text-ink2 cursor-pointer select-none min-h-[44px] sm:min-h-[36px]">
                            <input type="checkbox" checked={research} onChange={(e) => setResearch(e.target.checked)}
                                className="w-4 h-4 accent-[var(--color-accent)]" />
                            Web research (real numbers and sources)
                        </label>
                        <button type="button" onClick={writeScript} disabled={writing || !topic.trim()}
                            className="btn-primary sm:ml-auto">
                            {writing ? <><Loader2 size={16} className="animate-spin" aria-hidden="true" /> Writing…</> : (script ? 'Rewrite the script' : 'Write the script')}
                        </button>
                    </div>
                </section>

                {/* Script editor */}
                {script && (
                    <section aria-labelledby="story-script-title" className="card p-4 sm:p-6">
                        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 mb-5">
                            <h3 id="story-script-title" className="font-display text-lg text-ink">Script</h3>
                            <p className="readout">{script.scenes.length} scenes · {words} words · ~{Math.round(words / 2.5)}s</p>
                        </div>
                        <div className="grid sm:grid-cols-2 gap-4 mb-6">
                            <div>
                                <label htmlFor="story-yt-title" className="block text-sm font-medium text-ink mb-1.5">YouTube title</label>
                                <input id="story-yt-title" value={script.youtube_title || ''} onChange={(e) => setScript({ ...script, youtube_title: e.target.value })} className="input-field text-sm" />
                            </div>
                            <div>
                                <label htmlFor="story-hook" className="block text-sm font-medium text-ink mb-1.5">Hook</label>
                                <input id="story-hook" value={script.hook || ''} onChange={(e) => setScript({ ...script, hook: e.target.value })} className="input-field text-sm" />
                            </div>
                        </div>

                        <ol className="space-y-3">
                            {script.scenes.map((s, i) => (
                                <li key={i} className="tray p-3 sm:p-4">
                                    <div className="flex flex-wrap items-center gap-2 mb-3">
                                        <span className="font-quote text-3xl leading-none text-ink w-8 shrink-0" aria-hidden="true">{i + 1}</span>
                                        <span className="sr-only">Scene {i + 1}</span>
                                        <div role="group" aria-label={`Characters in scene ${i + 1}`} className="flex gap-1.5">
                                            {CAST.map((c) => (
                                                <button key={c.id} type="button" onClick={() => toggleCast(i, c.id)}
                                                    aria-pressed={(s.characters || []).includes(c.id)}
                                                    className={chip((s.characters || []).includes(c.id))}>{c.name}</button>
                                            ))}
                                        </div>
                                        <label htmlFor={`story-scene-${i}-emotion`} className="sr-only">Emotion, scene {i + 1}</label>
                                        <select id={`story-scene-${i}-emotion`} value={s.emotion} onChange={(e) => setScene(i, { emotion: e.target.value })} className="input-field !w-auto text-xs py-1.5">
                                            {EMOTIONS.map((x) => <option key={x} value={x}>{x}</option>)}
                                        </select>
                                        <label htmlFor={`story-scene-${i}-camera`} className="sr-only">Camera move, scene {i + 1}</label>
                                        <select id={`story-scene-${i}-camera`} value={s.camera} onChange={(e) => setScene(i, { camera: e.target.value })} className="input-field !w-auto text-xs py-1.5">
                                            {CAMERAS.map((x) => <option key={x} value={x}>{x.replace('_', ' ')}</option>)}
                                        </select>
                                        <span className="ml-auto flex gap-1">
                                            <button type="button" onClick={() => addScene(i)}
                                                className="w-11 h-11 sm:w-9 sm:h-9 rounded-input flex items-center justify-center text-muted hover:text-ink hover:bg-paper2 transition-colors"
                                                aria-label={`Add a scene after scene ${i + 1}`} title="Add a scene after">
                                                <Plus size={16} aria-hidden="true" />
                                            </button>
                                            <button type="button" onClick={() => removeScene(i)}
                                                className="w-11 h-11 sm:w-9 sm:h-9 rounded-input flex items-center justify-center text-muted hover:text-danger hover:bg-paper2 transition-colors"
                                                aria-label={`Remove scene ${i + 1}`} title="Remove scene">
                                                <Trash2 size={16} aria-hidden="true" />
                                            </button>
                                        </span>
                                    </div>
                                    <label htmlFor={`story-scene-${i}-narration`} className="readout block mb-1">Narration</label>
                                    <textarea id={`story-scene-${i}-narration`} value={s.narration} onChange={(e) => setScene(i, { narration: e.target.value })} rows={2}
                                        className="input-field text-sm" placeholder="What the voice says" />
                                    <div className="grid sm:grid-cols-[1fr_10rem] gap-3 mt-3">
                                        <div>
                                            <label htmlFor={`story-scene-${i}-visual`} className="readout block mb-1">Drawing</label>
                                            <input id={`story-scene-${i}-visual`} value={s.visual} onChange={(e) => setScene(i, { visual: e.target.value })}
                                                className="input-field text-sm" placeholder="What the drawing shows" />
                                        </div>
                                        <div>
                                            <label htmlFor={`story-scene-${i}-text`} className="readout block mb-1">Big text</label>
                                            <input id={`story-scene-${i}-text`} value={s.on_screen_text} onChange={(e) => setScene(i, { on_screen_text: e.target.value })}
                                                className="input-field text-sm" placeholder="e.g. $1.50" />
                                        </div>
                                    </div>
                                </li>
                            ))}
                        </ol>

                        {!!script.sources?.length && (
                            <details className="mt-5 pt-4 border-t border-rule">
                                <summary className="text-sm text-ink2 cursor-pointer hover:text-ink min-h-[44px] sm:min-h-0 flex items-center">
                                    Sources ({script.sources.length}) · check the numbers before posting
                                </summary>
                                <ul className="mt-3 space-y-1.5">
                                    {script.sources.map((src) => (
                                        <li key={src.url} className="text-sm min-w-0">
                                            <a href={src.url} target="_blank" rel="noopener noreferrer" className="text-cobalt underline underline-offset-2 hover:text-ink inline-flex items-center gap-1 break-all">
                                                {src.title || src.url} <ExternalLink size={12} aria-hidden="true" className="shrink-0" />
                                            </a>
                                        </li>
                                    ))}
                                </ul>
                            </details>
                        )}
                    </section>
                )}

                {/* Render */}
                {script && (
                    <section aria-labelledby="story-render-title" className="card-print p-4 sm:p-6 mb-10">
                        <SectionHead id="story-render-title" icon={<Clapperboard size={18} />} title="Make the video">
                            Voice, music and hashtags, then we narrate, animate and caption it.
                        </SectionHead>
                        <div className="grid sm:grid-cols-3 gap-4">
                            <div>
                                <label htmlFor="story-voice" className="block text-sm font-medium text-ink mb-1.5">Voice</label>
                                <select id="story-voice" value={voice} onChange={(e) => setVoice(e.target.value)} className="input-field text-sm">
                                    {(config?.voices || ['am_michael']).map((v) => <option key={v} value={v}>{v}</option>)}
                                </select>
                            </div>
                            <div>
                                <label htmlFor="story-niche" className="block text-sm font-medium text-ink mb-1.5">Niche <span className="font-normal text-muted">(for hashtags)</span></label>
                                <input id="story-niche" value={niche} onChange={(e) => setNiche(e.target.value)} className="input-field text-sm" />
                            </div>
                            <label className="flex items-center gap-2 text-sm text-ink2 cursor-pointer select-none min-h-[44px] sm:self-end sm:pb-1.5">
                                <input type="checkbox" checked={music} onChange={(e) => setMusic(e.target.checked)} className="w-4 h-4 accent-[var(--color-accent)]" />
                                Background music
                            </label>
                        </div>
                        {config && !config.kokoro && (
                            <p className="mt-4 px-3 py-2.5 rounded-input border border-warn/30 bg-warn/10 text-sm text-warn flex items-start gap-2">
                                <AlertTriangle size={16} className="shrink-0 mt-0.5" aria-hidden="true" />
                                <span>The free voice (Kokoro) isn&apos;t installed yet: the video will be silent, with captions timed on the script.</span>
                            </p>
                        )}
                        <p className="text-xs text-muted mt-3 leading-relaxed">Images are placeholders for now (your cast in the right pose). Real drawings come with Flux Kontext on the GPU PC.</p>

                        <div className="mt-5 pt-5 border-t border-rule">
                            <button type="button" onClick={render} disabled={rendering || !script.scenes.length}
                                className="btn-accent w-full sm:w-auto">
                                {rendering ? <><Loader2 size={16} className="animate-spin" aria-hidden="true" /> Rendering…</> : 'Generate video'}
                            </button>
                        </div>

                        <div aria-live="polite">
                            {job && (
                                <div className="mt-6">
                                    {job.status === 'processing' && <JobProgressBar progress={job.progress} />}
                                    {job.status === 'failed' && (
                                        <p role="alert" className="text-danger text-sm flex items-start gap-2 break-words">
                                            <AlertTriangle size={16} className="shrink-0 mt-0.5" aria-hidden="true" />
                                            <span className="min-w-0">Render failed: {(job.logs || []).slice(-1)[0]}</span>
                                        </p>
                                    )}
                                    {job.status === 'completed' && job.result && (
                                        <div className="flex flex-col sm:flex-row gap-5 items-start">
                                            <figure className="w-full sm:w-64 shrink-0">
                                                <video src={`${getApiUrl(job.result.video_url)}#t=0.1`} controls preload="metadata"
                                                    className="w-full aspect-[9/16] bg-black border border-rule2 rounded-card" />
                                                <figcaption className="readout mt-2">{job.result.duration}s · 9:16</figcaption>
                                            </figure>
                                            <div className="space-y-3 min-w-0">
                                                <p className="text-base font-semibold text-ink flex items-center gap-2">
                                                    <Check size={16} className="text-ok" aria-hidden="true" /> Done · {job.result.duration}s
                                                </p>
                                                <p className="text-sm text-muted leading-relaxed">Saved as a project: open it to restyle the captions, download it or schedule it on Upload-Post.</p>
                                                <button type="button" onClick={() => onOpenProject?.(job.id)} className="btn-primary">
                                                    Open in Clip Generator
                                                </button>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    </section>
                )}
            </div>
        </div>
    );
}

function SectionHead({ id, icon, title, children }) {
    return (
        <div className="flex items-start gap-3 mb-5">
            <span className="w-9 h-9 shrink-0 rounded-input bg-paper3 border border-rule flex items-center justify-center text-muted" aria-hidden="true">
                {icon}
            </span>
            <div className="min-w-0">
                <h3 id={id} className="font-display text-lg text-ink leading-tight">{title}</h3>
                {children && <p className="text-sm text-muted mt-1 leading-relaxed">{children}</p>}
            </div>
        </div>
    );
}

function SelectMark({ active }) {
    return (
        <span
            aria-hidden="true"
            className={`absolute top-3 right-3 w-5 h-5 rounded-full border flex items-center justify-center transition-colors duration-200 ${
                active ? 'bg-vermilion border-vermilion text-brassink' : 'bg-paper2 border-rule2'
            }`}
        >
            {active && <Check size={12} strokeWidth={2.5} />}
        </span>
    );
}
