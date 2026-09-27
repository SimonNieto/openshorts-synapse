import React, { useState, useEffect } from 'react';
import { Loader2, Languages, AlertCircle, Save, Plus, Star, Trash2 } from 'lucide-react';
import { apiFetch, apiJson } from '../lib/api';
import RemotionPreview from './RemotionPreview';
import {
    previewFontSizePx,
    previewBorderPx,
    previewLetterSpacingPx,
    previewFontWeight,
} from '../remotion/lib/assScale';
import Modal from './ui/Modal';
import SegmentedControl from './ui/SegmentedControl';
import { LANGUAGES } from './TranslateModal';

export const FONT_OPTIONS = [
    // Anton is the default caption face (subtitles.AUTO_CAPTION_STYLE) but was
    // missing from the picker, so the modal opened with nothing selected and
    // touching the control silently swapped the clip's font.
    { value: 'Anton', label: 'Anton' },
    { value: 'Verdana', label: 'Verdana' },
    { value: 'Arial', label: 'Arial' },
    { value: 'Impact', label: 'Impact' },
    { value: 'Helvetica', label: 'Helvetica' },
    { value: 'Georgia', label: 'Georgia' },
    { value: 'Courier New', label: 'Courier New' },
    // The dashboard's mono face (fonts/JetBrainsMono-Medium.ttf server-side).
    { value: 'JetBrains Mono', label: 'JetBrains Mono' },
];

export const COLOR_PRESETS = [
    { color: '#FFFFFF', label: 'White' },
    { color: '#FFFF00', label: 'Yellow' },
    { color: '#00FFFF', label: 'Cyan' },
    { color: '#00FF00', label: 'Green' },
    { color: '#FF0000', label: 'Red' },
    { color: '#FF69B4', label: 'Pink' },
];

export const HIGHLIGHT_PRESETS = [
    { color: '#FFDD00', label: 'Gold' },
    { color: '#FF4444', label: 'Red' },
    { color: '#00FF88', label: 'Green' },
    { color: '#00BBFF', label: 'Blue' },
    { color: '#FF69B4', label: 'Pink' },
];

const ANIMATION_OPTIONS = [
    { value: 'pop', label: 'Pop' },
    { value: 'word-highlight', label: 'Glow' },
    { value: 'karaoke', label: 'Karaoke' },
    { value: 'box', label: 'Box' },
    { value: 'highlight-box', label: 'Box Fill' },
    { value: 'none', label: 'None' },
];

// Ready-made caption looks burned server-side as karaoke ASS (word highlight):
// dimmed base text + strong active word, optional glow/pop/box effect.
export const CAPTION_PRESETS = [
    { id: 'tiktok',  label: 'TikTok',     style: 'karaoke', effect: 'none', highlightColor: '#FE2C55', baseOpacity: 0.75, uppercase: false, fontName: 'Verdana', borderWidth: 2 },
    { id: 'reels',   label: 'Reels',      style: 'karaoke', effect: 'none', highlightColor: '#E1306C', baseOpacity: 0.7,  uppercase: false, fontName: 'Verdana', borderWidth: 2 },
    { id: 'shorts',  label: 'Shorts Pop', style: 'karaoke', effect: 'pop',  highlightColor: '#FF0000', baseOpacity: 0.7,  uppercase: false, fontName: 'Verdana', borderWidth: 2 },
    { id: 'gold',    label: 'Gold Glow',  style: 'karaoke', effect: 'glow', highlightColor: '#FFD700', baseOpacity: 0.6,  uppercase: false, fontName: 'Verdana', borderWidth: 2 },
    { id: 'neon',    label: 'Neon',       style: 'karaoke', effect: 'glow', highlightColor: '#00FF88', baseOpacity: 0.55, uppercase: false, fontName: 'Verdana', borderWidth: 2 },
    { id: 'cyber',   label: 'Cyber',      style: 'karaoke', effect: 'glow', highlightColor: '#00FFFF', baseOpacity: 0.5,  uppercase: false, fontName: 'Verdana', borderWidth: 2 },
    { id: 'karaoke', label: 'Karaoke',    style: 'karaoke', effect: 'none', highlightColor: '#FF6B6B', baseOpacity: 0.6,  uppercase: false, fontName: 'Verdana', borderWidth: 2 },
    { id: 'minimal', label: 'Minimal',    style: 'karaoke', effect: 'none', highlightColor: '#FFFFFF', baseOpacity: 0.65, uppercase: false, fontName: 'Verdana', borderWidth: 1 },
    { id: 'beast',   label: 'Beast',      style: 'karaoke', effect: 'pop',  highlightColor: '#FFD700', baseOpacity: 1.0,  uppercase: true,  fontName: 'Impact',  borderWidth: 3 },
    { id: 'boxed',   label: 'Boxed',      style: 'karaoke', effect: 'box',  highlightColor: '#7C3AED', baseOpacity: 0.85, uppercase: false, fontName: 'Verdana', borderWidth: 2 },
    { id: 'capcut',  label: 'CapCut',     style: 'karaoke', effect: 'highlight-box', highlightColor: '#FFE500', baseOpacity: 0.85, uppercase: true, fontName: 'Anton', borderWidth: 3 },
    { id: 'classic', label: 'Classic',    style: 'classic', effect: 'none', highlightColor: '#FFD700', baseOpacity: 1.0,  uppercase: false, fontName: 'Verdana', borderWidth: 2 },
];

const swatchClass = (selected) =>
    `w-6 h-6 rounded-full transition-all ${selected
        ? 'ring-2 ring-[color:var(--color-accent)] ring-offset-2 ring-offset-[color:var(--color-paper-2)]'
        : 'ring-1 ring-[color:var(--color-rule-2)] hover:ring-[color:var(--color-accent)]'}`;

// Saved caption LOOKS the user built themselves (position/font/colors/effect),
// distinct from the fixed built-in CAPTION_PRESETS above. The one marked
// "default" is what a freshly opened editor starts from — edit it once here
// and every clip (including from a brand new generation) picks it up.
const SUBTITLE_PROFILES_KEY = 'openshorts_subtitle_profiles_v1';

// Mirrors subtitles.AUTO_CAPTION_STYLE — the look a clip gets automatically
// from the main pipeline, so a freshly opened editor (no saved profile yet)
// still starts matching what the user already sees on their clips.
function builtinDefaultSettings() {
    return {
        // 0-100, % of frame height up from the bottom (see subtitles.generate_ass's
        // position_percent) — 15 reproduces the old fixed "bottom" preset exactly.
        position: 15, fontName: 'Anton', fontColor: '#FFFFFF', highlightColor: '#FFE500',
        borderColor: '#000000', borderWidth: 4, bgColor: '#000000', bgOpacity: 0.0, animation: 'pop',
        style: 'karaoke', effect: 'pop', baseOpacity: 1.0, uppercase: true,
        fontSize: 44, letterSpacing: 0, maxWords: null,
    };
}

// A profile saved before "position" became a 0-100 slider still has the old
// 'top' | 'middle' | 'bottom' string — coerce it once on load so the range
// input (and the "N% from bottom" label) never renders that string raw.
const LEGACY_POSITION_PERCENT = { top: 85, middle: 50, bottom: 15 };
function normalizePosition(pos) {
    if (typeof pos === 'number') return pos;
    return LEGACY_POSITION_PERCENT[pos] ?? 15;
}

export function loadSubtitleProfileStore() {
    try {
        const raw = JSON.parse(localStorage.getItem(SUBTITLE_PROFILES_KEY) || 'null');
        if (raw && Array.isArray(raw.profiles) && raw.profiles.length) {
            return {
                ...raw,
                profiles: raw.profiles.map((p) => ({ ...p, settings: { ...p.settings, position: normalizePosition(p.settings.position) } })),
            };
        }
    } catch { /* ignore */ }
    return { profiles: [{ id: 'default', name: 'Default', settings: builtinDefaultSettings() }], defaultId: 'default' };
}

export function activeSubtitleProfileSettings(store) {
    return (store.profiles.find((p) => p.id === store.defaultId) || store.profiles[0]).settings;
}

export default function SubtitleModal({ isOpen, onClose, onGenerate, onApplyAll, onRemove, isProcessing, videoUrl, jobId, clipIndex, existingHook, bulkCount = 0, bulkProgress, geminiApiKey }) {
    // Defaults come from whichever subtitle profile is marked default (see
    // SUBTITLE_PROFILES_KEY above) — a freshly opened editor with no saved
    // profile yet starts from AUTO_CAPTION_STYLE, the look every clip
    // (including a freshly erased Viral Clip Reworker clip, which starts
    // with no captions at all) gets automatically from the main pipeline.
    const [subtitleProfileStore, setSubtitleProfileStore] = useState(loadSubtitleProfileStore);
    const [activeSubtitleProfileId, setActiveSubtitleProfileId] = useState(() => loadSubtitleProfileStore().defaultId);
    const initialSubtitle = activeSubtitleProfileSettings(subtitleProfileStore);
    const [position, setPosition] = useState(initialSubtitle.position);
    const [fontSize, setFontSize] = useState(initialSubtitle.fontSize);
    const [letterSpacing, setLetterSpacing] = useState(initialSubtitle.letterSpacing);
    const [maxWords, setMaxWords] = useState(initialSubtitle.maxWords);
    // subtitles.AUTO_CAPTION_STYLE's own values — were never sent at all
    // before, so the burn always fell back to generate_ass's own defaults
    // (20/2.0), which chunk captions differently than a real clip.
    const [maxChars] = useState(16);
    const [maxDuration] = useState(1.4);
    const [fontName, setFontName] = useState(initialSubtitle.fontName);
    const [fontColor, setFontColor] = useState(initialSubtitle.fontColor);
    const [highlightColor, setHighlightColor] = useState(initialSubtitle.highlightColor);
    const [borderColor, setBorderColor] = useState(initialSubtitle.borderColor);
    const [borderWidth, setBorderWidth] = useState(initialSubtitle.borderWidth);
    const [bgColor, setBgColor] = useState(initialSubtitle.bgColor);
    const [bgOpacity, setBgOpacity] = useState(initialSubtitle.bgOpacity);
    const [animation, setAnimation] = useState(initialSubtitle.animation);
    const [showTextEditor, setShowTextEditor] = useState(false);

    // Karaoke (server-side ASS burn) state
    const [style, setStyle] = useState(initialSubtitle.style); // classic | karaoke
    const [effect, setEffect] = useState(initialSubtitle.effect); // none | glow | pop | box
    const [baseOpacity, setBaseOpacity] = useState(initialSubtitle.baseOpacity);
    const [uppercase, setUppercase] = useState(initialSubtitle.uppercase);
    const [activePreset, setActivePreset] = useState(null);

    useEffect(() => {
        try { localStorage.setItem(SUBTITLE_PROFILES_KEY, JSON.stringify(subtitleProfileStore)); } catch { /* ignore */ }
    }, [subtitleProfileStore]);

    const currentSubtitleSettings = () => ({
        position, fontName, fontColor, highlightColor, borderColor, borderWidth,
        bgColor, bgOpacity, animation, style, effect, baseOpacity, uppercase,
        fontSize, letterSpacing, maxWords,
    });

    const applySettingsObject = (s) => {
        setPosition(s.position);
        setFontName(s.fontName);
        setFontColor(s.fontColor);
        setHighlightColor(s.highlightColor);
        setBorderColor(s.borderColor);
        setBorderWidth(s.borderWidth);
        setBgColor(s.bgColor);
        setBgOpacity(s.bgOpacity);
        setAnimation(s.animation);
        setStyle(s.style);
        setEffect(s.effect);
        setBaseOpacity(s.baseOpacity);
        setUppercase(s.uppercase);
        setFontSize(s.fontSize ?? 44);
        setLetterSpacing(s.letterSpacing ?? 0);
        setMaxWords(s.maxWords ?? null);
    };

    const applySubtitleProfile = (id) => {
        const p = subtitleProfileStore.profiles.find((pr) => pr.id === id);
        if (!p) return;
        setActiveSubtitleProfileId(id);
        setActivePreset(null);
        applySettingsObject(p.settings);
    };

    // This modal stays mounted (isOpen just toggles rendering — see the
    // `if (!isOpen) return null` below), so the useState() initializers above
    // only ever run once per clip's card and never see a profile saved
    // *after* that first mount. Re-read from disk and re-apply the current
    // default every time the editor is actually opened, so editing a profile
    // in one clip's editor and reopening ANY clip's (including a brand new
    // generation's) picks it up instead of the stale value from first mount.
    useEffect(() => {
        if (!isOpen) return;
        const store = loadSubtitleProfileStore();
        setSubtitleProfileStore(store);
        setActiveSubtitleProfileId(store.defaultId);
        setActivePreset(null);
        applySettingsObject(activeSubtitleProfileSettings(store));
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isOpen]);

    const handleSaveNewSubtitleProfile = () => {
        const name = window.prompt('Name this caption style:');
        if (!name || !name.trim()) return;
        const id = `sp_${Date.now()}`;
        setSubtitleProfileStore((prev) => ({
            ...prev,
            profiles: [...prev.profiles, { id, name: name.trim(), settings: currentSubtitleSettings() }],
        }));
        setActiveSubtitleProfileId(id);
    };

    const handleUpdateSubtitleProfile = () => {
        setSubtitleProfileStore((prev) => ({
            ...prev,
            profiles: prev.profiles.map((p) => (p.id === activeSubtitleProfileId ? { ...p, settings: currentSubtitleSettings() } : p)),
        }));
    };

    const handleSetDefaultSubtitleProfile = () => {
        setSubtitleProfileStore((prev) => ({ ...prev, defaultId: activeSubtitleProfileId }));
    };

    const handleDeleteSubtitleProfile = () => {
        if (subtitleProfileStore.profiles.length <= 1) return;
        if (!window.confirm('Delete this caption style?')) return;
        const remaining = subtitleProfileStore.profiles.filter((p) => p.id !== activeSubtitleProfileId);
        setSubtitleProfileStore((prev) => ({
            profiles: remaining,
            defaultId: prev.defaultId === activeSubtitleProfileId ? remaining[0].id : prev.defaultId,
        }));
        applySubtitleProfile(remaining[0].id);
    };

    const applyPreset = (p) => {
        setActivePreset(p.id);
        setStyle(p.style);
        setEffect(p.effect);
        setHighlightColor(p.highlightColor);
        setBaseOpacity(p.baseOpacity);
        setUppercase(p.uppercase);
        setFontName(p.fontName);
        setBorderWidth(p.borderWidth);
        setFontColor('#FFFFFF');
        setBgOpacity(0);
        // Keep the Remotion preview roughly in sync with the burned look
        setAnimation(p.style === 'karaoke'
            ? (p.effect === 'pop' ? 'pop' : p.effect === 'glow' ? 'word-highlight'
              : p.effect === 'box' ? 'box' : p.effect === 'highlight-box' ? 'highlight-box' : 'karaoke')
            : 'none');
    };

    // Remotion preview state
    const [captions, setCaptions] = useState([]);
    const [originalCaptions, setOriginalCaptions] = useState([]);
    const [editableText, setEditableText] = useState('');
    const [durationSec, setDurationSec] = useState(30);
    const [captionsLoading, setCaptionsLoading] = useState(false);
    const [useRemotionPreview, setUseRemotionPreview] = useState(false);

    // Caption translation: text only, voice stays original. Reuses the same
    // engine as the Viral Clip Reworker's "subtitles only" language picker,
    // exposed here so any clip's subtitle editor can translate on demand.
    const [translateLang, setTranslateLang] = useState('');
    const [translating, setTranslating] = useState(false);
    const [translateError, setTranslateError] = useState('');

    // Fetch word-level captions when modal opens
    useEffect(() => {
        if (!isOpen || !jobId || clipIndex === undefined) return;

        setCaptionsLoading(true);
        apiFetch(`/api/clip/${jobId}/${clipIndex}/transcript`)
            .then((res) => res.ok ? res.json() : null)
            .then((data) => {
                if (data && data.captions && data.captions.length > 0) {
                    setCaptions(data.captions);
                    setOriginalCaptions(data.captions);
                    setEditableText(data.captions.map(c => c.text).join(' '));
                    setDurationSec(data.durationSec || 30);
                    setUseRemotionPreview(true);
                } else {
                    setUseRemotionPreview(false);
                }
            })
            .catch(() => setUseRemotionPreview(false))
            .finally(() => setCaptionsLoading(false));
    }, [isOpen, jobId, clipIndex]);

    // When user edits text, redistribute words across original timestamps
    const handleTextEdit = (newText) => {
        setEditableText(newText);
        const newWords = newText.split(/\s+/).filter(w => w.length > 0);
        if (newWords.length === 0 || originalCaptions.length === 0) {
            setCaptions([]);
            return;
        }

        // Distribute new words across the time span of original captions
        const totalDurationMs = originalCaptions[originalCaptions.length - 1].endMs - originalCaptions[0].startMs;
        const startMs = originalCaptions[0].startMs;
        const wordDurationMs = totalDurationMs / newWords.length;

        const newCaptions = newWords.map((word, i) => ({
            text: word,
            startMs: Math.round(startMs + i * wordDurationMs),
            endMs: Math.round(startMs + (i + 1) * wordDurationMs),
        }));
        setCaptions(newCaptions);
    };

    // Fetches translated captions and drops them into `captions`/`editableText`
    // ONLY — `originalCaptions` deliberately stays the pre-translation
    // baseline. The burn ("apply to this clip") already sends the edited
    // `captions` array whenever `editableText` differs from that baseline
    // (see styleOptions.captions below); translating is just another way to
    // produce an edit, so it needs no new persistence or burn path.
    const handleTranslate = async () => {
        if (!translateLang || !jobId || clipIndex === undefined) return;
        const apiKey = geminiApiKey || localStorage.getItem('gemini_key');
        if (!apiKey) {
            setTranslateError('Set your Gemini API key in Settings first.');
            return;
        }
        setTranslating(true);
        setTranslateError('');
        try {
            const data = await apiJson(`/api/clip/${jobId}/${clipIndex}/translate-captions`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Gemini-Key': apiKey },
                body: JSON.stringify({ target_language: translateLang }),
            });
            if (!data.captions || data.captions.length === 0) {
                throw new Error('No captions came back');
            }
            setCaptions(data.captions);
            setEditableText(data.captions.map((c) => c.text).join(' '));
            setShowTextEditor(true);
        } catch (e) {
            setTranslateError(e.detail || e.message || 'Translation failed');
        } finally {
            setTranslating(false);
        }
    };

    if (!isOpen) return null;

    // Build subtitle config for Remotion
    const subtitleConfig = {
        captions,
        position,
        // Caption-block chunking — without these the preview always grouped
        // words with groupCaptionsIntoBlocks' own hardcoded defaults (20
        // chars / 2s / no word cap), so "Max Words" and "Letter Spacing"
        // visibly did nothing here even though the real server-side burn
        // already honored them.
        maxChars,
        maxDurationMs: maxDuration * 1000,
        maxWords,
        style: {
            fontFamily: fontName,
            // Sizes go through the same two steps the burn does (see
            // assScale.ts): the *2.2 / *1.5 factors these replace were never
            // derived from libass, so the editor drew captions ~45% smaller
            // than the file it was previewing, with an outline 4x too thin.
            fontSize: previewFontSizePx(fontSize),
            letterSpacing: previewLetterSpacingPx(letterSpacing),
            fontWeight: previewFontWeight(fontName),
            fontColor,
            highlightColor,
            borderColor,
            borderWidth: previewBorderPx(borderWidth),
            bgColor,
            bgOpacity,
            animation,
            // Karaoke look reflected live in the playable preview.
            baseOpacity: style === 'karaoke' ? baseOpacity : 1,
            uppercase: style === 'karaoke' ? uppercase : false,
        },
    };

    // Fallback: static CSS preview (same as original)
    const bw = Math.max(borderWidth, 0);
    const bc = borderColor;
    const outlineShadow = bw > 0 ? [
        `-${bw}px -${bw}px 0 ${bc}`, `${bw}px -${bw}px 0 ${bc}`,
        `-${bw}px ${bw}px 0 ${bc}`, `${bw}px ${bw}px 0 ${bc}`,
        `0 -${bw}px 0 ${bc}`, `0 ${bw}px 0 ${bc}`,
        `-${bw}px 0 0 ${bc}`, `${bw}px 0 0 ${bc}`,
    ].join(', ') : 'none';

    const fallbackPreviewStyle = {
        fontFamily: fontName,
        color: fontColor,
        fontSize: '20px',
        fontWeight: 'bold',
        maxWidth: '85%',
        padding: '6px 12px',
        borderRadius: '4px',
        textAlign: 'center',
        lineHeight: '1.3',
        ...(bgOpacity > 0
            ? {
                backgroundColor: `${bgColor}${Math.round(bgOpacity * 255).toString(16).padStart(2, '0')}`,
                textShadow: 'none',
            }
            : { textShadow: outlineShadow }
        ),
    };

    return (
        <Modal isOpen={isOpen} onClose={onClose} size="xl" eyebrow="EDITOR · SUBTITLES" title="subtitles">
            <div className="flex flex-col md:flex-row gap-6">
                {/* Left: Preview — sticky so it stays visible while the
                    (often long) controls column scrolls past it. */}
                <div className="flex-1 flex flex-col items-center justify-center bg-black rounded-card border border-rule overflow-hidden relative aspect-[9/16] max-h-[600px] sticky top-0 self-start">
                    {captionsLoading ? (
                        <div className="flex items-center gap-2 text-muted">
                            <Loader2 size={16} className="animate-spin" />
                            <span className="text-sm lowercase">Loading preview...</span>
                        </div>
                    ) : useRemotionPreview ? (
                        <RemotionPreview
                            videoUrl={videoUrl}
                            durationInSeconds={durationSec}
                            subtitles={subtitleConfig}
                            hook={existingHook || null}
                        />
                    ) : (
                        <>
                            <video src={videoUrl} className="w-full h-full object-contain opacity-50" muted playsInline />
                            <div className={`absolute w-full px-8 text-center transition-all duration-300 pointer-events-none flex flex-col items-center justify-center
                                ${position === 'top' ? 'top-20' : ''}
                                ${position === 'middle' ? 'top-0 bottom-0' : ''}
                                ${position === 'bottom' ? 'bottom-20' : ''}
                            `}>
                                <span style={fallbackPreviewStyle}>
                                    This is how your subtitles<br/>will appear on the video
                                </span>
                            </div>
                        </>
                    )}
                </div>

                {/* Right: Controls */}
                <div className="w-full md:w-80 flex flex-col">
                    <div className="space-y-5 flex-1 overflow-y-auto custom-scrollbar pr-1">
                        {/* Caption presets (server-side karaoke burn) */}
                        <div>
                            <p className="eyebrow mb-2">Preset</p>
                            <div className="grid grid-cols-3 gap-1.5">
                                {CAPTION_PRESETS.map((p) => (
                                    <button
                                        key={p.id}
                                        onClick={() => applyPreset(p)}
                                        className={`px-2 py-1.5 rounded-input border text-xs transition-colors flex items-center gap-1.5 justify-center
                                            ${activePreset === p.id
                                                ? 'border-[color:var(--color-accent)] text-ink'
                                                : 'border-rule2 text-muted hover:border-[color:var(--color-accent)]'}`}
                                        title={p.label}
                                    >
                                        <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: p.highlightColor }} />
                                        {p.label}
                                    </button>
                                ))}
                            </div>
                            {style === 'karaoke' && (
                                <div className="mt-3 space-y-3 animate-fade">
                                    <div className="flex items-center justify-between">
                                        <span className="readout">UPPERCASE</span>
                                        <label className="relative inline-flex items-center cursor-pointer">
                                            <input type="checkbox" checked={uppercase} onChange={(e) => setUppercase(e.target.checked)} className="sr-only peer" />
                                            <div className="w-8 h-4 rounded-full bg-paper3 peer-checked:bg-brass transition-colors after:content-[''] after:absolute after:top-0 after:left-0 after:h-4 after:w-4 after:rounded-full after:bg-ink after:transition-all peer-checked:after:translate-x-full"></div>
                                        </label>
                                    </div>
                                    <div>
                                        <div className="flex justify-between mb-1">
                                            <span className="readout">Dim inactive words</span>
                                            <span className="readout">{Math.round(baseOpacity * 100)}%</span>
                                        </div>
                                        <input
                                            type="range"
                                            min="30"
                                            max="100"
                                            value={Math.round(baseOpacity * 100)}
                                            onChange={(e) => setBaseOpacity(parseInt(e.target.value) / 100)}
                                            className="w-full accent-[var(--color-accent)]"
                                        />
                                    </div>
                                </div>
                            )}
                        </div>

                        {/* Your own saved caption styles — edit one, mark it
                            default, and every clip's editor (including a
                            brand new generation) opens with it pre-loaded. */}
                        <div>
                            <p className="eyebrow mb-2">My Profiles</p>
                            <div className="flex flex-wrap items-center gap-2">
                                <select
                                    value={activeSubtitleProfileId}
                                    onChange={(e) => applySubtitleProfile(e.target.value)}
                                    className="input-field !w-auto text-xs py-1.5 flex-1 min-w-[100px]"
                                    aria-label="caption style profile"
                                >
                                    {subtitleProfileStore.profiles.map((p) => (
                                        <option key={p.id} value={p.id}>
                                            {p.name}{p.id === subtitleProfileStore.defaultId ? ' (default)' : ''}
                                        </option>
                                    ))}
                                </select>
                                <button type="button" onClick={handleUpdateSubtitleProfile} className="btn-ghost px-2 py-1.5 text-xs shrink-0" title="Save the style below into this profile">
                                    <Save size={13} />
                                </button>
                                <button type="button" onClick={handleSaveNewSubtitleProfile} className="btn-ghost px-2 py-1.5 text-xs shrink-0" title="Save the style below as a new profile">
                                    <Plus size={13} />
                                </button>
                                <button
                                    type="button"
                                    onClick={handleSetDefaultSubtitleProfile}
                                    disabled={activeSubtitleProfileId === subtitleProfileStore.defaultId}
                                    className="btn-ghost px-2 py-1.5 text-xs shrink-0 disabled:opacity-40"
                                    title="Use this style automatically every time the editor opens"
                                >
                                    <Star size={13} className={activeSubtitleProfileId === subtitleProfileStore.defaultId ? 'fill-current text-brass' : ''} />
                                </button>
                                {subtitleProfileStore.profiles.length > 1 && (
                                    <button type="button" onClick={handleDeleteSubtitleProfile} className="btn-ghost px-2 py-1.5 text-xs shrink-0 text-danger" title="Delete this profile">
                                        <Trash2 size={13} />
                                    </button>
                                )}
                            </div>
                        </div>

                        {/* Position — a slider instead of top/middle/bottom
                            presets, so it can be pinned exactly where wanted. */}
                        <div>
                            <div className="flex justify-between mb-1">
                                <p className="eyebrow">Position</p>
                                <span className="readout">{position}% from bottom</span>
                            </div>
                            <input
                                type="range"
                                min="0"
                                max="92"
                                value={position}
                                onChange={(e) => setPosition(parseInt(e.target.value, 10))}
                                className="w-full accent-[var(--color-accent)]"
                            />
                            <div className="flex justify-between">
                                <span className="readout">bottom</span>
                                <span className="readout">top</span>
                            </div>
                        </div>

                        {/* Animation Style — this drives BOTH the live preview
                            (`animation`) and the real server-side burn
                            (`style`/`effect`); they used to be unsynced, so
                            picking "Karaoke" here still shipped whatever
                            `effect` a preset had last set (usually "pop"). */}
                        <div>
                            <p className="eyebrow mb-2">Animation</p>
                            <SegmentedControl
                                options={ANIMATION_OPTIONS}
                                value={animation}
                                onChange={(v) => {
                                    setAnimation(v);
                                    setActivePreset(null);
                                    if (v === 'none') {
                                        setStyle('classic');
                                        setEffect('none');
                                    } else {
                                        setStyle('karaoke');
                                        setEffect(
                                            v === 'pop' ? 'pop'
                                            : v === 'word-highlight' ? 'glow'
                                            : v === 'box' ? 'box'
                                            : v === 'highlight-box' ? 'highlight-box'
                                            : 'none'
                                        );
                                    }
                                }}
                                columns={2}
                                size="sm"
                            />
                        </div>

                        {/* Translate captions: text only, voice stays original */}
                        {useRemotionPreview && (
                            <div>
                                <p className="eyebrow mb-2">Translate captions</p>
                                <div className="flex gap-2">
                                    <select
                                        value={translateLang}
                                        onChange={(e) => setTranslateLang(e.target.value)}
                                        className="input-field flex-1 appearance-none cursor-pointer"
                                        disabled={translating}
                                    >
                                        <option value="">choose a language...</option>
                                        {Object.entries(LANGUAGES).sort((a, b) => a[1].localeCompare(b[1])).map(([code, name]) => (
                                            <option key={code} value={code}>{name}</option>
                                        ))}
                                    </select>
                                    <button
                                        onClick={handleTranslate}
                                        disabled={!translateLang || translating}
                                        className="btn-ghost px-3 shrink-0 disabled:opacity-40"
                                        title="translate the caption text only — the voice stays as-is"
                                    >
                                        {translating ? <Loader2 size={16} className="animate-spin" /> : <Languages size={16} />}
                                    </button>
                                </div>
                                {translateError && (
                                    <p className="text-danger text-xs mt-1.5 flex items-center gap-1">
                                        <AlertCircle size={12} /> {translateError}
                                    </p>
                                )}
                                <p className="text-xs text-muted mt-1.5">
                                    Translates the text only — the spoken voice is unaffected. For dubbing the voice
                                    itself, use "dub voice" instead.
                                </p>
                            </div>
                        )}

                        {/* Editable Transcript (collapsible) */}
                        {useRemotionPreview && (
                            <div>
                                <button
                                    type="button"
                                    onClick={() => setShowTextEditor(!showTextEditor)}
                                    className="w-full flex items-center justify-between mb-2"
                                >
                                    <span className="eyebrow">Edit text ({captions.length} words)</span>
                                    <span className={`text-muted transition-transform ${showTextEditor ? 'rotate-180' : ''}`}>▾</span>
                                </button>
                                {showTextEditor && (
                                    <textarea
                                        value={editableText}
                                        onChange={(e) => handleTextEdit(e.target.value)}
                                        rows={5}
                                        className="input-field resize-none leading-relaxed animate-fade"
                                        placeholder="Edit subtitle text..."
                                    />
                                )}
                            </div>
                        )}

                        {/* Font Family */}
                        <div>
                            <p className="eyebrow mb-2">Font</p>
                            <select
                                value={fontName}
                                onChange={(e) => setFontName(e.target.value)}
                                className="input-field"
                            >
                                {FONT_OPTIONS.map((f) => (
                                    <option key={f.value} value={f.value} style={{ fontFamily: f.value }}>{f.label}</option>
                                ))}
                            </select>
                        </div>

                        {/* Text Size */}
                        <div>
                            <div className="flex justify-between mb-1">
                                <p className="eyebrow">Text Size</p>
                                <span className="readout">{fontSize}px</span>
                            </div>
                            <input
                                type="range"
                                min="20"
                                max="80"
                                value={fontSize}
                                onChange={(e) => setFontSize(parseInt(e.target.value, 10))}
                                className="w-full accent-[var(--color-accent)]"
                            />
                        </div>

                        {/* Letter Spacing */}
                        <div>
                            <div className="flex justify-between mb-1">
                                <p className="eyebrow">Letter Spacing</p>
                                <span className="readout">{letterSpacing}px</span>
                            </div>
                            <input
                                type="range"
                                min="-3"
                                max="15"
                                value={letterSpacing}
                                onChange={(e) => setLetterSpacing(parseInt(e.target.value, 10))}
                                className="w-full accent-[var(--color-accent)]"
                            />
                        </div>

                        {/* Max words per caption block — breaks a block early
                            regardless of character count when set. */}
                        <div>
                            <div className="flex justify-between mb-1">
                                <p className="eyebrow">Max Words</p>
                                <span className="readout">{maxWords ? maxWords : 'unlimited'}</span>
                            </div>
                            <input
                                type="range"
                                min="0"
                                max="8"
                                value={maxWords ?? 0}
                                onChange={(e) => {
                                    const v = parseInt(e.target.value, 10);
                                    setMaxWords(v === 0 ? null : v);
                                }}
                                className="w-full accent-[var(--color-accent)]"
                            />
                            <div className="flex justify-between">
                                <span className="readout">unlimited</span>
                                <span className="readout">8 words</span>
                            </div>
                        </div>

                        {/* Text Color */}
                        <div>
                            <p className="eyebrow mb-2">Text color</p>
                            <div className="flex flex-wrap items-center gap-2.5">
                                {COLOR_PRESETS.map((c) => (
                                    <button
                                        key={c.color}
                                        onClick={() => setFontColor(c.color)}
                                        className={swatchClass(fontColor === c.color)}
                                        style={{ backgroundColor: c.color }}
                                        title={c.label}
                                    />
                                ))}
                                <label className="w-6 h-6 rounded-full border border-dashed border-rule2 cursor-pointer flex items-center justify-center hover:border-brass transition-colors overflow-hidden relative" title="Custom color">
                                    <span className="text-xs text-muted leading-none">+</span>
                                    <input type="color" value={fontColor} onChange={(e) => setFontColor(e.target.value)} className="absolute inset-0 opacity-0 cursor-pointer" />
                                </label>
                            </div>
                        </div>

                        {/* Highlight Color (new) */}
                        <div>
                            <p className="eyebrow mb-2">Highlight</p>
                            <div className="flex flex-wrap items-center gap-2.5">
                                {HIGHLIGHT_PRESETS.map((c) => (
                                    <button
                                        key={c.color}
                                        onClick={() => setHighlightColor(c.color)}
                                        className={swatchClass(highlightColor === c.color)}
                                        style={{ backgroundColor: c.color }}
                                        title={c.label}
                                    />
                                ))}
                            </div>
                        </div>

                        {/* Border / Outline */}
                        <div>
                            <p className="eyebrow mb-2">Border</p>
                            <div className="flex items-center gap-3">
                                <label className="relative w-8 h-8 rounded-input border border-rule2 cursor-pointer overflow-hidden shrink-0" title="Border color">
                                    <div className="w-full h-full" style={{ backgroundColor: borderColor }} />
                                    <input type="color" value={borderColor} onChange={(e) => setBorderColor(e.target.value)} className="absolute inset-0 opacity-0 cursor-pointer" />
                                </label>
                                <div className="flex-1">
                                    <input
                                        type="range"
                                        min="0"
                                        max="5"
                                        value={borderWidth}
                                        onChange={(e) => setBorderWidth(parseInt(e.target.value))}
                                        className="w-full accent-[var(--color-accent)]"
                                    />
                                    <div className="flex justify-between">
                                        <span className="readout">None</span>
                                        <span className="readout">Thick</span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* Background Box */}
                        <div>
                            <div className="flex items-center justify-between mb-2">
                                <p className="eyebrow">Background</p>
                                <label className="relative inline-flex items-center cursor-pointer">
                                    <input type="checkbox" checked={bgOpacity > 0} onChange={(e) => setBgOpacity(e.target.checked ? 0.5 : 0)} className="sr-only peer" />
                                    <div className="w-8 h-4 rounded-full bg-paper3 peer-checked:bg-brass transition-colors after:content-[''] after:absolute after:top-0 after:left-0 after:h-4 after:w-4 after:rounded-full after:bg-ink after:transition-all peer-checked:after:translate-x-full"></div>
                                </label>
                            </div>
                            {bgOpacity > 0 && (
                                <div className="space-y-3 animate-fade">
                                    <div className="flex items-center gap-3">
                                        <label className="relative w-8 h-8 rounded-input border border-rule2 cursor-pointer overflow-hidden shrink-0" title="Background color">
                                            <div className="w-full h-full" style={{ backgroundColor: bgColor }} />
                                            <input type="color" value={bgColor} onChange={(e) => setBgColor(e.target.value)} className="absolute inset-0 opacity-0 cursor-pointer" />
                                        </label>
                                        <div className="flex-1">
                                            <input
                                                type="range"
                                                min="10"
                                                max="100"
                                                value={Math.round(bgOpacity * 100)}
                                                onChange={(e) => setBgOpacity(parseInt(e.target.value) / 100)}
                                                className="w-full accent-[var(--color-accent)]"
                                            />
                                            <div className="flex justify-between">
                                                <span className="readout">Transparent</span>
                                                <span className="readout">{Math.round(bgOpacity * 100)}%</span>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>

                    <div className="mt-5 shrink-0 space-y-2">
                        {(() => {
                            // Text edits must survive the server render path too
                            // (issue #69): send the edited words whenever the text
                            // differs from what the transcript produced.
                            const textEdited = originalCaptions.length > 0
                                && editableText.trim() !== originalCaptions.map((c) => c.text).join(' ').trim();
                            const styleOptions = {
                                position, positionPercent: position, fontSize, fontName, fontColor, borderColor, borderWidth, bgColor, bgOpacity,
                                maxChars, maxDuration, letterSpacing, maxWords,
                                // Karaoke burn (server-side ASS render)
                                style, effect, baseOpacity, uppercase, highlightColor,
                                // Remotion data
                                remotion: useRemotionPreview ? subtitleConfig : null,
                                captions: textEdited ? captions : null,
                            };
                            const bulkRunning = bulkProgress?.running;
                            return (
                                <>
                                    <div className="flex gap-2">
                                        <button onClick={onClose} className="btn-ghost">
                                            cancel
                                        </button>
                                        <button
                                            onClick={() => onGenerate(styleOptions)}
                                            disabled={isProcessing}
                                            className="btn-primary flex-1"
                                        >
                                            {(isProcessing && !bulkRunning) && <Loader2 size={16} className="animate-spin text-brassink" />}
                                            {(isProcessing && !bulkRunning) ? 'generating...' : 'apply to this clip'}
                                        </button>
                                    </div>
                                    {onApplyAll && bulkCount > 1 && (
                                        <button
                                            onClick={() => onApplyAll({ ...styleOptions, captions: null })}
                                            disabled={isProcessing}
                                            className="btn-ghost w-full flex items-center justify-center gap-2"
                                        >
                                            {bulkRunning
                                                ? <><Loader2 size={16} className="animate-spin" />applying to all… {bulkProgress.current}/{bulkProgress.total}</>
                                                : `apply this style to all ${bulkCount} clips`}
                                        </button>
                                    )}
                                    {/* Clips ship captioned by default, so the way
                                        out has to be here — otherwise a user who
                                        doesn't want captions is stuck with them. */}
                                    {onRemove && (
                                        <button
                                            onClick={onRemove}
                                            disabled={isProcessing}
                                            className="text-xs text-muted underline underline-offset-2 lowercase hover:text-ink2 disabled:opacity-50"
                                        >
                                            remove captions from this clip
                                        </button>
                                    )}
                                </>
                            );
                        })()}
                    </div>
                </div>
            </div>
        </Modal>
    );
}
