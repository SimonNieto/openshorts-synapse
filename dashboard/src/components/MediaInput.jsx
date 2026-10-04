import React, { useState, useEffect, useRef, useId } from 'react';
import { Link2, Upload, FileVideo, X, Info, Loader2, ChevronDown, AlertTriangle } from 'lucide-react';
import { getApiUrl } from '../config';
import AutoPublishOption from './AutoPublishOption';
import SegmentedControl from './ui/SegmentedControl';
import { loadAutoPublish, saveAutoPublish } from '../lib/autoPublish';

const SUPPORTED_PLATFORMS = [
    'YouTube', 'Vimeo', 'TikTok', 'X / Twitter', 'Twitch',
    'Facebook', 'Instagram', 'Dailymotion', 'Reddit', 'Streamable',
];

const FORMATS = [
    { value: 'vertical', label: '9:16', hint: 'Shorts · Reels · TikTok', w: 13, h: 23 },
    { value: 'square', label: '1:1', hint: 'Feed posts', w: 20, h: 20 },
    { value: 'horizontal', label: '16:9', hint: 'Keep landscape · YouTube', w: 26, h: 15 },
];

const formatSize = (bytes) => {
    if (!Number.isFinite(bytes)) return '';
    const mb = bytes / 1048576;
    return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb >= 10 ? Math.round(mb) : mb.toFixed(1)} MB`;
};

export default function MediaInput({ onProcess, isProcessing, publishProfiles = [], defaultProfile = '', canAutoPublish = false, plusProfile = null }) {
    const [youtubeUrlEnabled, setYoutubeUrlEnabled] = useState(true);
    // File upload is the primary path; the link is secondary.
    const [mode, setMode] = useState('file'); // 'file' | 'url'
    const [url, setUrl] = useState('');
    const [file, setFile] = useState(null);
    const [acknowledged, setAcknowledged] = useState(false);
    const [outputFormat, setOutputFormat] = useState('vertical'); // vertical | horizontal | square
    const [showInfo, setShowInfo] = useState(false);
    // Advanced generation controls — empty string means "let the AI decide",
    // which keeps the default pipeline behavior untouched.
    const [showAdvanced, setShowAdvanced] = useState(false);
    const [targetClips, setTargetClips] = useState('');
    const [clipMinSeconds, setClipMinSeconds] = useState('');
    const [clipMaxSeconds, setClipMaxSeconds] = useState('');
    // Auto-hook: burn the AI hook text into every clip. On by default; the
    // choice persists so turning it off sticks across sessions.
    const [autoHook, setAutoHook] = useState(() => {
        try { return localStorage.getItem('os_auto_hook') !== '0'; } catch { return true; }
    });
    const [autoHookStyle, setAutoHookStyle] = useState(() => {
        try { return localStorage.getItem('os_auto_hook_style') || 'classic'; } catch { return 'classic'; }
    });
    // Layout: 'auto' lets the AI pick per video (server default); the others
    // force one on so a podcast host who knows what they uploaded doesn't
    // depend on the detector, and 'none' keeps the plain single crop.
    const [layout, setLayout] = useState(() => {
        try { return localStorage.getItem('os_layout') || 'auto'; } catch { return 'auto'; }
    });
    // Publish the best clips on Upload-Post as soon as the job ends.
    const [autoPublish, setAutoPublish] = useState(loadAutoPublish);
    const infoRef = useRef(null);
    // Purely visual: lights the drop zone while a file is dragged over it.
    const [dragOver, setDragOver] = useState(false);
    const uid = useId();
    const ids = {
        source: `${uid}-source`,
        url: `${uid}-url`,
        urlHint: `${uid}-url-hint`,
        platforms: `${uid}-platforms`,
        file: `${uid}-file`,
        fileHint: `${uid}-file-hint`,
        format: `${uid}-format`,
        advanced: `${uid}-advanced`,
        target: `${uid}-target`,
        min: `${uid}-min`,
        max: `${uid}-max`,
        layout: `${uid}-layout`,
        submitHint: `${uid}-submit-hint`,
    };

    // Close the compatibility popover on any outside click.
    useEffect(() => {
        if (!showInfo) return;
        const onClick = (e) => {
            if (infoRef.current && !infoRef.current.contains(e.target)) setShowInfo(false);
        };
        document.addEventListener('mousedown', onClick);
        return () => document.removeEventListener('mousedown', onClick);
    }, [showInfo]);

    useEffect(() => {
        fetch(getApiUrl('/api/config'))
            .then((r) => r.ok ? r.json() : null)
            .then((cfg) => {
                if (cfg && cfg.youtubeUrlEnabled === false) {
                    setYoutubeUrlEnabled(false);
                    setMode('file');
                }
            })
            .catch(() => {});
    }, []);

    // A link pasted in the landing hero: preload it here so the user picks up
    // where they left off. Not auto-submitted — the rights attestation below
    // has to be ticked by the user.
    useEffect(() => {
        let pending = null;
        try {
            pending = localStorage.getItem('os_pending_url');
            if (pending) localStorage.removeItem('os_pending_url');
        } catch { /* ignore */ }
        if (pending) {
            setMode('url');
            setUrl(pending);
        }
    }, []);

    const handleSubmit = (e) => {
        e.preventDefault();
        if (!acknowledged) return;
        const advanced = {
            targetClips: targetClips || null,
            clipMinSeconds: clipMinSeconds || null,
            clipMaxSeconds: clipMaxSeconds || null,
            autoHook,
            autoHookStyle,
            layout,
            autoPublish: canAutoPublish && autoPublish.enabled
                ? { ...autoPublish, profile: autoPublish.profile || defaultProfile || publishProfiles[0]?.username || '' }
                : null,
        };
        // Synapse Cut: the profile carries the recipe (the server reads it
        // by id) and its own auto-publish settings.
        if (plusProfile) {
            // Count, lengths and hook come from the profile: the (now hidden)
            // fields must not leak a stale value into the job.
            advanced.targetClips = null;
            advanced.clipMinSeconds = null;
            advanced.clipMaxSeconds = null;
            advanced.plusProfileId = plusProfile.id;
            const ap = plusProfile.auto_publish || {};
            advanced.autoPublish = canAutoPublish && ap.enabled
                ? {
                    enabled: true,
                    platforms: ap.platforms,
                    niche: plusProfile.niche || '',
                    profile: plusProfile.upload_profile || defaultProfile || publishProfiles[0]?.username || '',
                }
                : null;
        }
        try {
            localStorage.setItem('os_auto_hook', autoHook ? '1' : '0');
            localStorage.setItem('os_auto_hook_style', autoHookStyle);
            localStorage.setItem('os_layout', layout);
        } catch { /* ignore */ }
        saveAutoPublish(autoPublish);
        if (mode === 'url' && url) {
            onProcess({ type: 'url', payload: url, acknowledged: true, outputFormat, ...advanced });
        } else if (mode === 'file' && file) {
            onProcess({ type: 'file', payload: file, acknowledged: true, outputFormat, ...advanced });
        }
    };

    const handleDrop = (e) => {
        e.preventDefault();
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            setFile(e.dataTransfer.files[0]);
            setMode('file');
        }
    };

    const hasSource = (mode === 'url' && !!url) || (mode === 'file' && !!file);
    const notVideo = mode === 'file' && file && file.type && !file.type.startsWith('video/');
    const advancedEdited = !!(targetClips || clipMinSeconds || clipMaxSeconds || !autoHook);

    const sourceOptions = [
        { value: 'file', label: 'Upload a file', icon: <Upload size={16} /> },
        ...(youtubeUrlEnabled ? [{ value: 'url', label: 'Paste a link', icon: <Link2 size={16} /> }] : []),
    ];

    return (
        <div className="card-print p-4 sm:p-6 text-left animate-fade">
            {/* Where the video comes from */}
            <div className="mb-5" data-tutorial="source-tabs" role="group" aria-labelledby={ids.source}>
                <p id={ids.source} className="readout mb-2">Source</p>
                <SegmentedControl
                    options={sourceOptions}
                    value={mode}
                    onChange={setMode}
                    columns={sourceOptions.length}
                    size="sm"
                />
            </div>

            <form onSubmit={handleSubmit}>
                {mode === 'url' ? (
                    <div className="space-y-2" data-tutorial="drop-zone">
                        <label htmlFor={ids.url} className="block text-sm font-medium text-ink">Video link</label>
                        <div className="relative">
                            <input
                                id={ids.url}
                                type="url"
                                value={url}
                                onChange={(e) => setUrl(e.target.value)}
                                placeholder="https://… paste a video link"
                                className="input-field pr-12"
                                aria-describedby={ids.urlHint}
                                required
                            />
                            <div className="absolute inset-y-0 right-1.5 flex items-center" ref={infoRef}>
                                <button
                                    type="button"
                                    onClick={() => setShowInfo((v) => !v)}
                                    aria-label="Supported platforms"
                                    aria-expanded={showInfo}
                                    aria-controls={ids.platforms}
                                    className="h-9 w-9 inline-flex items-center justify-center rounded-input text-muted hover:text-ink hover:bg-paper3 transition-colors"
                                >
                                    <Info size={16} aria-hidden="true" />
                                </button>
                                {showInfo && (
                                    <div id={ids.platforms} className="absolute right-0 top-full mt-2 w-64 max-w-[calc(100vw-3rem)] z-20 card p-4 text-left animate-fade">
                                        <p className="readout mb-2">Paste a link from</p>
                                        <ul className="flex flex-wrap gap-1.5">
                                            {SUPPORTED_PLATFORMS.map((p) => (
                                                <li key={p} className="text-xs px-2 py-0.5 rounded-[4px] border border-rule bg-paper3 text-ink2">
                                                    {p}
                                                </li>
                                            ))}
                                        </ul>
                                        <p className="text-xs text-muted mt-2.5 leading-relaxed">
                                            …and 1,000+ more sites. If a link has a public video, we can usually fetch it.
                                        </p>
                                    </div>
                                )}
                            </div>
                        </div>
                        <p id={ids.urlHint} className="text-xs text-muted">
                            A public video on YouTube, TikTok, Instagram, Vimeo and many more.
                        </p>
                    </div>
                ) : (
                    <div
                        data-tutorial="drop-zone"
                        className={`rounded-card border border-dashed transition-colors duration-200
                            has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-[color:var(--color-focus)]
                            ${dragOver
                                ? 'border-vermilion bg-vermilionsoft'
                                : file
                                    ? 'border-rule2 bg-paper3'
                                    : 'border-rule2 hover:border-ink/40 hover:bg-paper3'}`}
                        onDragOver={(e) => { e.preventDefault(); if (!dragOver) setDragOver(true); }}
                        onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setDragOver(false); }}
                        onDrop={(e) => { setDragOver(false); handleDrop(e); }}
                    >
                        {file ? (
                            <div className="flex items-center gap-3 p-3 sm:p-4 min-w-0">
                                <span aria-hidden="true" className="h-10 w-10 shrink-0 rounded-input border border-rule2 bg-paper2 flex items-center justify-center text-ink">
                                    <FileVideo size={18} />
                                </span>
                                <div className="min-w-0 flex-1">
                                    <p className="text-sm font-medium text-ink truncate" title={file.name}>{file.name}</p>
                                    <p className="readout mt-0.5">{formatSize(file.size)} · Ready to go</p>
                                </div>
                                <button
                                    type="button"
                                    onClick={() => setFile(null)}
                                    aria-label={`Remove ${file.name}`}
                                    className="h-11 w-11 sm:h-9 sm:w-9 shrink-0 inline-flex items-center justify-center rounded-input text-muted hover:text-ink hover:bg-paper2 transition-colors"
                                >
                                    <X size={16} aria-hidden="true" />
                                </button>
                            </div>
                        ) : (
                            <label htmlFor={ids.file} className="flex flex-col items-center justify-center gap-2 px-4 py-8 sm:py-10 text-center cursor-pointer">
                                <input
                                    id={ids.file}
                                    type="file"
                                    accept="video/*"
                                    onChange={(e) => setFile(e.target.files?.[0] || null)}
                                    aria-describedby={ids.fileHint}
                                    className="sr-only"
                                />
                                <span aria-hidden="true" className={`mb-1 h-11 w-11 rounded-full border flex items-center justify-center transition-colors ${dragOver ? 'border-vermilion text-vermilion' : 'border-rule2 text-ink2'}`}>
                                    <Upload size={18} />
                                </span>
                                <span className="text-sm font-medium text-ink">
                                    {dragOver ? 'Drop to add this video' : 'Drop a video here, or choose a file'}
                                </span>
                                <span id={ids.fileHint} className="readout">MP4, MOV · up to 500 MB</span>
                            </label>
                        )}
                    </div>
                )}

                {notVideo && (
                    <p role="alert" className="mt-2 flex items-start gap-2 text-sm text-warn">
                        <AlertTriangle size={15} aria-hidden="true" className="shrink-0 mt-0.5" />
                        This file doesn’t look like a video. Clip Generator needs an MP4, MOV or another video file.
                    </p>
                )}

                {/* Output format selector */}
                <div className="mt-6" data-tutorial="output-format" role="group" aria-labelledby={ids.format}>
                    <p id={ids.format} className="readout mb-2">Output format</p>
                    <SegmentedControl
                        options={FORMATS.map((f) => ({
                            value: f.value,
                            label: f.label,
                            hint: f.hint,
                            // aspect-ratio glyph, drawn in the button's own colour
                            icon: (
                                <span
                                    className="block rounded-[3px] border-[1.5px] border-current"
                                    style={{ width: `${f.w}px`, height: `${f.h}px` }}
                                />
                            ),
                        }))}
                        value={outputFormat}
                        onChange={setOutputFormat}
                        columns={3}
                    />
                </div>

                {/* Advanced generation controls — collapsed by default; blank = AI decides */}
                <div className="mt-5 pt-1 border-t border-rule">
                    <button
                        type="button"
                        onClick={() => setShowAdvanced((v) => !v)}
                        aria-expanded={showAdvanced}
                        aria-controls={ids.advanced}
                        className="mt-2 inline-flex items-center gap-2 min-h-[40px] [@media(pointer:coarse)]:min-h-[44px] text-sm text-ink2 hover:text-ink transition-colors"
                    >
                        <ChevronDown size={16} aria-hidden="true" className={`transition-transform duration-200 ${showAdvanced ? 'rotate-180' : ''}`} />
                        Advanced options
                        {advancedEdited && <span className="readout">· Edited</span>}
                    </button>
                    {showAdvanced && (
                        /* Stacked on a phone: three number fields side by side leaves
                           ~100px each, which crushes both label and value. */
                        <div id={ids.advanced} className="mt-2 grid grid-cols-1 sm:grid-cols-3 gap-3 animate-fade">
                            {plusProfile ? (
                                <p className="col-span-1 sm:col-span-3 text-xs leading-relaxed text-muted">
                                    Clip count, clip lengths and hook titles come from the selected
                                    Synapse Cut profile (edit them there).
                                </p>
                            ) : (<>
                            <div>
                                <label htmlFor={ids.target} className="block text-xs font-medium text-ink2 mb-1.5">Clips to aim for</label>
                                <input
                                    id={ids.target}
                                    type="number" min="1" max="15" step="1"
                                    value={targetClips}
                                    onChange={(e) => setTargetClips(e.target.value)}
                                    placeholder="Auto"
                                    className="input-field"
                                />
                            </div>
                            <div>
                                <label htmlFor={ids.min} className="block text-xs font-medium text-ink2 mb-1.5">Min length (s)</label>
                                <input
                                    id={ids.min}
                                    type="number" min="5" max="175" step="1"
                                    value={clipMinSeconds}
                                    onChange={(e) => setClipMinSeconds(e.target.value)}
                                    placeholder="15"
                                    className="input-field"
                                />
                            </div>
                            <div>
                                <label htmlFor={ids.max} className="block text-xs font-medium text-ink2 mb-1.5">Max length (s)</label>
                                <input
                                    id={ids.max}
                                    type="number" min="10" max="180" step="1"
                                    value={clipMaxSeconds}
                                    onChange={(e) => setClipMaxSeconds(e.target.value)}
                                    placeholder="60"
                                    className="input-field"
                                />
                            </div>
                            <p className="col-span-1 sm:col-span-3 text-xs leading-relaxed text-muted">
                                Targets, not guarantees: the AI returns fewer clips when the
                                material doesn't hold them. Leave blank to let it decide.
                            </p>
                            </>)}
                            <div className="col-span-1 sm:col-span-3 flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-rule">
                                <label htmlFor={ids.layout} className="text-sm text-ink2">Vertical layout</label>
                                <select
                                    id={ids.layout}
                                    value={layout}
                                    onChange={(e) => setLayout(e.target.value)}
                                    className="input-field !w-auto text-sm py-2"
                                >
                                    <option value="auto">Auto (AI picks per video)</option>
                                    <option value="split">Two speakers stacked</option>
                                    <option value="screencast">Screen over presenter</option>
                                    <option value="none">Single crop only</option>
                                </select>
                            </div>
                            {!plusProfile && (
                            <div className="col-span-1 sm:col-span-3 flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-rule">
                                <label className="flex items-center gap-2.5 min-h-[40px] text-sm text-ink2 cursor-pointer select-none">
                                    <input
                                        type="checkbox"
                                        checked={autoHook}
                                        onChange={(e) => setAutoHook(e.target.checked)}
                                        className="w-4 h-4 shrink-0 accent-[var(--color-accent)] cursor-pointer"
                                    />
                                    Auto hook titles on clips
                                </label>
                                {autoHook && (
                                    <select
                                        value={autoHookStyle}
                                        onChange={(e) => setAutoHookStyle(e.target.value)}
                                        aria-label="Hook title style"
                                        className="input-field !w-auto text-sm py-2"
                                    >
                                        <option value="classic">Classic</option>
                                        <option value="dark">Dark</option>
                                        <option value="yellow">Yellow</option>
                                        <option value="red">Red</option>
                                        <option value="outline">Outline</option>
                                        <option value="outline_yellow">Outline+</option>
                                    </select>
                                )}
                            </div>
                            )}
                        </div>
                    )}
                </div>

                {!plusProfile && (
                    <AutoPublishOption
                        value={autoPublish}
                        onChange={setAutoPublish}
                        profiles={publishProfiles}
                        defaultProfile={defaultProfile}
                        available={canAutoPublish}
                    />
                )}

                <label className="flex items-start gap-3 mt-5 text-left text-[13px] leading-relaxed text-muted cursor-pointer select-none">
                    <input
                        type="checkbox"
                        checked={acknowledged}
                        onChange={(e) => setAcknowledged(e.target.checked)}
                        className="mt-0.5 w-4 h-4 shrink-0 accent-[var(--color-accent)] cursor-pointer"
                    />
                    <span>
                        I confirm I own this content or have the rights to process it. I am responsible for any content I submit. See our <a href="/terms" target="_blank" rel="noopener noreferrer" className="text-ink2 underline underline-offset-2 hover:text-ink transition-colors" onClick={(e) => e.stopPropagation()}>Terms</a> and <a href="/privacy" target="_blank" rel="noopener noreferrer" className="text-ink2 underline underline-offset-2 hover:text-ink transition-colors" onClick={(e) => e.stopPropagation()}>Privacy Policy</a>.
                    </span>
                </label>

                <button
                    type="submit"
                    data-tutorial="generate"
                    disabled={isProcessing || !acknowledged || (mode === 'url' && !url) || (mode === 'file' && !file)}
                    aria-describedby={!isProcessing && (!hasSource || !acknowledged) ? ids.submitHint : undefined}
                    className="w-full btn-accent mt-4"
                >
                    {isProcessing ? (
                        <>
                            <Loader2 size={16} className="animate-spin" aria-hidden="true" />
                            Processing video…
                        </>
                    ) : (
                        <>
                            {plusProfile
                                ? `Generate with “${plusProfile.name}”`
                                : (canAutoPublish && autoPublish.enabled ? 'Generate & publish the 3 best' : 'Generate clips')}
                        </>
                    )}
                </button>
                {!isProcessing && (!hasSource || !acknowledged) && (
                    <p id={ids.submitHint} className="mt-2 text-xs text-muted text-center">
                        {!hasSource
                            ? (mode === 'url' ? 'Paste a video link to start.' : 'Add a video to start.')
                            : 'Confirm you have the rights to this video to start.'}
                    </p>
                )}
            </form>
        </div>
    );
}
