import React, { useEffect, useRef, useState } from 'react';
import { Loader2, Lightbulb, Link2, ImagePlus, PenLine, Trash2, Plus, Clapperboard, ExternalLink, X, AlertTriangle } from 'lucide-react';
import { apiFetch, apiJson } from '../lib/api';
import { getApiUrl } from '../config';
import JobProgressBar from './JobProgressBar';
import { loadSubtitleProfileStore, activeSubtitleProfileSettings } from './SubtitleModal';

// The draft survives leaving the tab (per-browser convenience only).
const DRAFT_KEY = 'os_story_draft_v1';
const loadDraft = () => { try { return JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null'); } catch { return null; } };
const saveDraft = (d) => { try { localStorage.setItem(DRAFT_KEY, JSON.stringify(d)); } catch { /* ignore */ } };

const EMOTIONS = ['neutral', 'shocked', 'explaining', 'happy', 'sad', 'confused', 'angry'];
const CAMERAS = ['zoom_in', 'zoom_out', 'pan_left', 'pan_right', 'static'];
const CAST = [{ id: 'casey', name: 'Casey' }, { id: 'prof', name: 'Prof. Margin' }];

const chip = (active) => `readout px-2.5 py-1.5 rounded-full border transition-colors ${active
    ? 'bg-brass/20 text-brass border-brass/50'
    : 'bg-paper3 text-ink2 border-transparent hover:border-rule2'}`;

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
        <div className="max-w-5xl mx-auto p-4 sm:p-6 md:p-8 animate-fade">
            <p className="eyebrow mb-1.5">STORY CHANNEL · HIDDEN ECONOMICS</p>
            <h1 className="font-display lowercase text-2xl text-ink mb-2">2D story videos</h1>
            <p className="text-muted text-sm mb-6 lowercase">
                Casey falls for the trap, Prof. Margin explains it. Idea → script you can edit → narrated, animated, captioned short.
            </p>

            {error && (
                <div className="mb-4 px-3 py-2.5 rounded-input border border-danger/40 bg-danger/10 text-danger text-sm flex items-start gap-2">
                    <AlertTriangle size={15} className="shrink-0 mt-0.5" /> <span className="break-words min-w-0">{error}</span>
                </div>
            )}

            {/* 1 · Inspiration */}
            <section className="card p-5 mb-5">
                <p className="text-sm text-ink font-medium lowercase flex items-center gap-2 mb-3">
                    <Lightbulb size={15} className="text-brass" /> inspiration · learn from a channel that works
                </p>
                <div className="grid md:grid-cols-2 gap-3">
                    <div className="flex gap-2">
                        <input value={channelUrl} onChange={(e) => setChannelUrl(e.target.value)}
                            placeholder="@thepaintexplainer or channel link" className="input-field text-sm" />
                        <button type="button" onClick={() => findIdeas('link')} disabled={ideasBusy || !channelUrl.trim()}
                            className="btn-quiet px-3 py-2 text-xs shrink-0 inline-flex items-center gap-1.5">
                            <Link2 size={14} /> analyze
                        </button>
                    </div>
                    <div className="flex gap-2 items-center">
                        <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={(e) => pickShot(e.target.files?.[0])} />
                        <button type="button" onClick={() => fileRef.current?.click()} className="btn-ghost px-3 py-2 text-xs inline-flex items-center gap-1.5 min-w-0">
                            <ImagePlus size={14} /> {shot ? 'screenshot ready' : 'or a screenshot of a channel'}
                        </button>
                        {shot && (
                            <>
                                <button type="button" onClick={() => setShot(null)} className="text-muted hover:text-ink" aria-label="remove screenshot"><X size={14} /></button>
                                <button type="button" onClick={() => findIdeas('shot')} disabled={ideasBusy}
                                    className="btn-quiet px-3 py-2 text-xs shrink-0">analyze</button>
                            </>
                        )}
                    </div>
                </div>
                <input value={hint} onChange={(e) => setHint(e.target.value)}
                    placeholder="optional direction, e.g. 'more about food and supermarkets'" className="input-field text-sm mt-2" />
                {ideasBusy && <p className="text-xs text-muted mt-3 flex items-center gap-2"><Loader2 size={13} className="animate-spin" /> reading the channel and finding angles…</p>}

                {ideas && !ideasBusy && (
                    <div className="mt-4 space-y-3">
                        {ideas.channel && <p className="readout">{ideas.channel}</p>}
                        {!!ideas.patterns?.length && (
                            <ul className="text-xs text-ink2 space-y-1 list-disc pl-4">
                                {ideas.patterns.map((p) => <li key={p}>{p}</li>)}
                            </ul>
                        )}
                        <div className="grid sm:grid-cols-2 gap-2">
                            {(ideas.ideas || []).map((idea) => (
                                <button key={idea.topic} type="button" onClick={() => setTopic(idea.topic)}
                                    className={`text-left p-3 rounded-input border transition-colors ${topic === idea.topic ? 'border-brass bg-brass/10' : 'border-rule hover:border-rule2 bg-paper'}`}>
                                    <p className="text-sm text-ink">{idea.topic}</p>
                                    <p className="text-xs text-muted mt-1">{idea.angle}</p>
                                    <p className="readout mt-1.5 normal-case">↳ {idea.why}</p>
                                </button>
                            ))}
                        </div>
                    </div>
                )}
            </section>

            {/* 2 · Topic → script */}
            <section className="card p-5 mb-5">
                <p className="text-sm text-ink font-medium lowercase flex items-center gap-2 mb-3">
                    <PenLine size={15} className="text-brass" /> topic
                </p>
                <textarea value={topic} onChange={(e) => setTopic(e.target.value)} rows={2}
                    placeholder="e.g. Why gyms make more money when you never show up" className="input-field text-sm" />
                <div className="flex flex-wrap items-center gap-2 mt-3">
                    {[45, 60, 75].map((s) => (
                        <button key={s} type="button" onClick={() => setSeconds(s)} className={chip(seconds === s)}>{s}s</button>
                    ))}
                    <label className="flex items-center gap-2 text-xs text-ink2 ml-2 cursor-pointer select-none">
                        <input type="checkbox" checked={research} onChange={(e) => setResearch(e.target.checked)}
                            className="w-4 h-4 accent-[var(--color-accent)]" />
                        web research (real numbers + sources)
                    </label>
                    <button type="button" onClick={writeScript} disabled={writing || !topic.trim()}
                        className="btn-primary px-4 py-2 text-xs ml-auto">
                        {writing ? <><Loader2 size={14} className="animate-spin" /> writing…</> : (script ? 'rewrite script' : 'write script')}
                    </button>
                </div>
            </section>

            {/* 3 · Script editor */}
            {script && (
                <section className="card p-5 mb-5">
                    <div className="flex flex-wrap items-baseline justify-between gap-2 mb-3">
                        <p className="text-sm text-ink font-medium lowercase">script · {script.scenes.length} scenes · {words} words (~{Math.round(words / 2.5)}s)</p>
                    </div>
                    <div className="grid sm:grid-cols-2 gap-2 mb-4">
                        <label className="block">
                            <span className="eyebrow">youtube title</span>
                            <input value={script.youtube_title || ''} onChange={(e) => setScript({ ...script, youtube_title: e.target.value })} className="input-field text-sm mt-1" />
                        </label>
                        <label className="block">
                            <span className="eyebrow">hook</span>
                            <input value={script.hook || ''} onChange={(e) => setScript({ ...script, hook: e.target.value })} className="input-field text-sm mt-1" />
                        </label>
                    </div>

                    <div className="space-y-2.5">
                        {script.scenes.map((s, i) => (
                            <div key={i} className="p-3 rounded-input border border-rule bg-paper">
                                <div className="flex items-center gap-2 mb-2">
                                    <span className="readout w-6">{i + 1}</span>
                                    {CAST.map((c) => (
                                        <button key={c.id} type="button" onClick={() => toggleCast(i, c.id)} className={chip((s.characters || []).includes(c.id))}>{c.name}</button>
                                    ))}
                                    <select value={s.emotion} onChange={(e) => setScene(i, { emotion: e.target.value })} className="input-field !w-auto text-xs py-1">
                                        {EMOTIONS.map((x) => <option key={x} value={x}>{x}</option>)}
                                    </select>
                                    <select value={s.camera} onChange={(e) => setScene(i, { camera: e.target.value })} className="input-field !w-auto text-xs py-1">
                                        {CAMERAS.map((x) => <option key={x} value={x}>{x.replace('_', ' ')}</option>)}
                                    </select>
                                    <span className="ml-auto flex gap-1">
                                        <button type="button" onClick={() => addScene(i)} className="p-1 text-muted hover:text-ink" title="add a scene after"><Plus size={14} /></button>
                                        <button type="button" onClick={() => removeScene(i)} className="p-1 text-muted hover:text-danger" title="remove scene"><Trash2 size={14} /></button>
                                    </span>
                                </div>
                                <textarea value={s.narration} onChange={(e) => setScene(i, { narration: e.target.value })} rows={2}
                                    className="input-field text-sm" placeholder="narration (what the voice says)" />
                                <div className="grid sm:grid-cols-[1fr_10rem] gap-2 mt-2">
                                    <input value={s.visual} onChange={(e) => setScene(i, { visual: e.target.value })}
                                        className="input-field text-xs" placeholder="what the drawing shows" />
                                    <input value={s.on_screen_text} onChange={(e) => setScene(i, { on_screen_text: e.target.value })}
                                        className="input-field text-xs" placeholder="big text, e.g. $1.50" />
                                </div>
                            </div>
                        ))}
                    </div>

                    {!!script.sources?.length && (
                        <details className="mt-4">
                            <summary className="text-xs text-muted cursor-pointer lowercase">sources ({script.sources.length}) · check the numbers before posting</summary>
                            <ul className="mt-2 space-y-1">
                                {script.sources.map((src) => (
                                    <li key={src.url} className="text-xs">
                                        <a href={src.url} target="_blank" rel="noopener noreferrer" className="text-ink2 underline underline-offset-2 hover:text-brass inline-flex items-center gap-1">
                                            {src.title || src.url} <ExternalLink size={11} />
                                        </a>
                                    </li>
                                ))}
                            </ul>
                        </details>
                    )}
                </section>
            )}

            {/* 4 · Render */}
            {script && (
                <section className="card p-5 mb-10">
                    <p className="text-sm text-ink font-medium lowercase flex items-center gap-2 mb-3">
                        <Clapperboard size={15} className="text-brass" /> make the video
                    </p>
                    <div className="grid sm:grid-cols-3 gap-3">
                        <label className="block">
                            <span className="eyebrow">voice</span>
                            <select value={voice} onChange={(e) => setVoice(e.target.value)} className="input-field text-sm mt-1">
                                {(config?.voices || ['am_michael']).map((v) => <option key={v} value={v}>{v}</option>)}
                            </select>
                        </label>
                        <label className="block">
                            <span className="eyebrow">niche · hashtags</span>
                            <input value={niche} onChange={(e) => setNiche(e.target.value)} className="input-field text-sm mt-1" />
                        </label>
                        <label className="flex items-end gap-2 text-xs text-ink2 cursor-pointer select-none pb-2">
                            <input type="checkbox" checked={music} onChange={(e) => setMusic(e.target.checked)} className="w-4 h-4 accent-[var(--color-accent)]" />
                            background music
                        </label>
                    </div>
                    {config && !config.kokoro && (
                        <p className="text-xs text-brass mt-3">The free voice (Kokoro) isn't installed yet: the video will be SILENT, with captions timed on the script.</p>
                    )}
                    <p className="text-xs text-muted mt-1">Images are placeholders for now (your cast in the right pose) — real drawings come with Flux Kontext on the GPU PC.</p>

                    <button type="button" onClick={render} disabled={rendering || !script.scenes.length}
                        className="btn-primary px-4 py-2 text-sm mt-4">
                        {rendering ? <><Loader2 size={15} className="animate-spin" /> rendering…</> : 'generate video'}
                    </button>

                    {job && (
                        <div className="mt-5">
                            {job.status === 'processing' && <JobProgressBar progress={job.progress} />}
                            {job.status === 'failed' && (
                                <p className="text-danger text-sm">Render failed: {(job.logs || []).slice(-1)[0]}</p>
                            )}
                            {job.status === 'completed' && job.result && (
                                <div className="flex flex-col sm:flex-row gap-4 items-start">
                                    <video src={`${getApiUrl(job.result.video_url)}#t=0.1`} controls preload="metadata"
                                        className="w-full sm:w-64 aspect-[9/16] bg-black rounded-card" />
                                    <div className="space-y-2">
                                        <p className="text-sm text-ink">Done · {job.result.duration}s</p>
                                        <p className="text-xs text-muted">Saved as a project: open it to restyle captions, download or schedule it on Upload-Post.</p>
                                        <button type="button" onClick={() => onOpenProject?.(job.id)} className="btn-quiet px-3 py-2 text-xs inline-flex items-center gap-1.5">
                                            open in clip generator
                                        </button>
                                    </div>
                                </div>
                            )}
                        </div>
                    )}
                </section>
            )}
        </div>
    );
}
