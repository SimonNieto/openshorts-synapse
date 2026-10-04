import React, { useState, useEffect, useId } from 'react';
import { Loader2, Languages, AlertCircle, Save, Plus, Star, Trash2, ChevronDown } from 'lucide-react';
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

    const uid = useId();

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
    const isDefaultProfile = activeSubtitleProfileId === subtitleProfileStore.defaultId;

    const footer = (
        <div className="flex flex-wrap items-center justify-end gap-2">
            <p className="sr-only" aria-live="polite">
                {bulkRunning
                    ? `Applying to all clips: ${bulkProgress.current} of ${bulkProgress.total}`
                    : isProcessing ? 'Applying the captions…' : ''}
            </p>
            {onApplyAll && bulkCount > 1 && (
                <button
                    type="button"
                    onClick={() => onApplyAll({ ...styleOptions, captions: null })}
                    disabled={isProcessing}
                    className="btn-ghost w-full sm:w-auto sm:mr-auto"
                >
                    {bulkRunning
                        ? <><Loader2 size={16} className="animate-spin" aria-hidden="true" />Applying to all… <span className="font-mono tabular-nums">{bulkProgress.current}/{bulkProgress.total}</span></>
                        : `Apply this style to all ${bulkCount} clips`}
                </button>
            )}
            <button type="button" onClick={onClose} className="btn-ghost flex-1 sm:flex-none">
                Cancel
            </button>
            <button
                type="button"
                onClick={() => onGenerate(styleOptions)}
                disabled={isProcessing}
                className="btn-accent flex-[2] sm:flex-none sm:min-w-[11rem]"
            >
                {(isProcessing && !bulkRunning) && <Loader2 size={16} className="animate-spin" aria-hidden="true" />}
                {(isProcessing && !bulkRunning) ? 'Applying…' : 'Apply to this clip'}
            </button>
        </div>
    );

    return (
        <Modal isOpen={isOpen} onClose={onClose} size="xl" title="Caption style" footer={footer}>
            <div className="grid gap-6 md:grid-cols-[minmax(0,1fr)_20rem] lg:grid-cols-[minmax(0,1fr)_23rem] md:items-start">
                {/* Preview — sticky so it stays visible while the (often long)
                    controls column scrolls past it. */}
                <figure className="md:sticky md:top-0 flex flex-col items-center gap-2 min-w-0">
                    <div className="relative flex flex-col items-center justify-center bg-black border border-rule2 rounded-card overflow-hidden aspect-[9/16] h-[50vh] sm:h-[min(600px,62vh)] max-w-full">
                        {captionsLoading ? (
                            <div role="status" className="flex items-center gap-2 text-ink2">
                                <Loader2 size={16} className="animate-spin" aria-hidden="true" />
                                <span className="text-sm">Loading preview…</span>
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
                    <figcaption className="readout">Preview · 9:16</figcaption>
                </figure>

                {/* Controls */}
                <div className="space-y-4 min-w-0">
                    {/* Caption presets (server-side karaoke burn) */}
                    <Group title="Style">
                        <div role="group" aria-labelledby={`${uid}-preset`}>
                            <p id={`${uid}-preset`} className="text-xs font-medium text-ink2 mb-2">Preset</p>
                            <div className="grid grid-cols-3 gap-1.5">
                                {CAPTION_PRESETS.map((p) => {
                                    const active = activePreset === p.id;
                                    return (
                                        <button
                                            key={p.id}
                                            type="button"
                                            onClick={() => applyPreset(p)}
                                            aria-pressed={active}
                                            className={`min-h-[36px] [@media(pointer:coarse)]:min-h-[44px] px-2 py-1.5 rounded-input border text-xs flex items-center gap-1.5 justify-center transition-colors duration-200
                                                ${active
                                                    ? 'border-ink bg-ink text-paper2 font-semibold'
                                                    : 'border-rule2 bg-paper2 text-ink2 hover:text-ink hover:border-ink'}`}
                                        >
                                            <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: p.highlightColor }} aria-hidden="true" />
                                            <span className="truncate">{p.label}</span>
                                        </button>
                                    );
                                })}
                            </div>
                        </div>
                        {style === 'karaoke' && (
                            <div className="pt-4 border-t border-rule space-y-4 animate-fade">
                                <Switch
                                    label="Uppercase"
                                    checked={uppercase}
                                    onChange={(e) => setUppercase(e.target.checked)}
                                />
                                <Slider
                                    label="Dim inactive words"
                                    valueText={`${Math.round(baseOpacity * 100)}%`}
                                    min="30"
                                    max="100"
                                    value={Math.round(baseOpacity * 100)}
                                    onChange={(e) => setBaseOpacity(parseInt(e.target.value) / 100)}
                                />
                            </div>
                        )}
                    </Group>

                    {/* Your own saved caption styles — edit one, mark it
                        default, and every clip's editor (including a
                        brand new generation) opens with it pre-loaded. */}
                    <Group title="Saved styles">
                        <div>
                            <label htmlFor={`${uid}-profile`} className="block text-xs font-medium text-ink2 mb-2">Caption style profile</label>
                            <select
                                id={`${uid}-profile`}
                                value={activeSubtitleProfileId}
                                onChange={(e) => applySubtitleProfile(e.target.value)}
                                aria-describedby={`${uid}-profile-hint`}
                                className="input-field"
                            >
                                {subtitleProfileStore.profiles.map((p) => (
                                    <option key={p.id} value={p.id}>
                                        {p.name}{p.id === subtitleProfileStore.defaultId ? ' (default)' : ''}
                                    </option>
                                ))}
                            </select>
                            <p id={`${uid}-profile-hint`} className="mt-2 text-xs text-muted leading-relaxed">
                                The default style opens automatically every time you edit captions.
                            </p>
                        </div>
                        <div className="grid grid-cols-2 gap-1.5">
                            <button type="button" onClick={handleUpdateSubtitleProfile} className="btn-ghost !px-2.5 !py-2 text-xs" title="Save the style below into this profile">
                                <Save size={14} aria-hidden="true" /> Update
                            </button>
                            <button type="button" onClick={handleSaveNewSubtitleProfile} className="btn-ghost !px-2.5 !py-2 text-xs" title="Save the style below as a new profile">
                                <Plus size={14} aria-hidden="true" /> Save as new
                            </button>
                            <button
                                type="button"
                                onClick={handleSetDefaultSubtitleProfile}
                                disabled={isDefaultProfile}
                                className="btn-ghost !px-2.5 !py-2 text-xs"
                                title="Use this style automatically every time the editor opens"
                            >
                                <Star size={14} className={isDefaultProfile ? 'fill-current' : ''} aria-hidden="true" />
                                {isDefaultProfile ? 'Default' : 'Make default'}
                            </button>
                            {subtitleProfileStore.profiles.length > 1 && (
                                <button type="button" onClick={handleDeleteSubtitleProfile} className="btn-danger !px-2.5 !py-2 text-xs" title="Delete this profile">
                                    <Trash2 size={14} aria-hidden="true" /> Delete
                                </button>
                            )}
                        </div>
                    </Group>

                    <Group title="Position and motion">
                        {/* Position — a slider instead of top/middle/bottom
                            presets, so it can be pinned exactly where wanted. */}
                        <Slider
                            label="Height"
                            valueText={`${position}% from bottom`}
                            min="0"
                            max="92"
                            value={position}
                            onChange={(e) => setPosition(parseInt(e.target.value, 10))}
                            minLabel="Bottom"
                            maxLabel="Top"
                        />

                        {/* Animation Style — this drives BOTH the live preview
                            (`animation`) and the real server-side burn
                            (`style`/`effect`); they used to be unsynced, so
                            picking "Karaoke" here still shipped whatever
                            `effect` a preset had last set (usually "pop"). */}
                        <div role="group" aria-labelledby={`${uid}-anim`}>
                            <p id={`${uid}-anim`} className="text-xs font-medium text-ink2 mb-2">Animation</p>
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
                                columns={3}
                                size="sm"
                            />
                        </div>
                    </Group>

                    <Group title="Type">
                        {/* Font Family */}
                        <div>
                            <label htmlFor={`${uid}-font`} className="block text-xs font-medium text-ink2 mb-2">Font</label>
                            <select
                                id={`${uid}-font`}
                                value={fontName}
                                onChange={(e) => setFontName(e.target.value)}
                                className="input-field"
                            >
                                {FONT_OPTIONS.map((f) => (
                                    <option key={f.value} value={f.value} style={{ fontFamily: f.value }}>{f.label}</option>
                                ))}
                            </select>
                        </div>

                        <Slider
                            label="Size"
                            valueText={`${fontSize}px`}
                            min="20"
                            max="80"
                            value={fontSize}
                            onChange={(e) => setFontSize(parseInt(e.target.value, 10))}
                        />

                        <Slider
                            label="Letter spacing"
                            valueText={`${letterSpacing}px`}
                            min="-3"
                            max="15"
                            value={letterSpacing}
                            onChange={(e) => setLetterSpacing(parseInt(e.target.value, 10))}
                        />

                        {/* Max words per caption block — breaks a block early
                            regardless of character count when set. */}
                        <Slider
                            label="Max words per caption"
                            valueText={maxWords ? `${maxWords} words` : 'Unlimited'}
                            min="0"
                            max="8"
                            value={maxWords ?? 0}
                            onChange={(e) => {
                                const v = parseInt(e.target.value, 10);
                                setMaxWords(v === 0 ? null : v);
                            }}
                            minLabel="Unlimited"
                            maxLabel="8 words"
                        />
                    </Group>

                    <Group title="Color">
                        {/* Text Color */}
                        <div role="group" aria-labelledby={`${uid}-color`}>
                            <p id={`${uid}-color`} className="text-xs font-medium text-ink2 mb-1">Text</p>
                            <div className="flex flex-wrap items-center gap-0.5 -ml-1.5">
                                {COLOR_PRESETS.map((c) => (
                                    <Swatch
                                        key={c.color}
                                        color={c.color}
                                        label={c.label}
                                        selected={fontColor === c.color}
                                        onClick={() => setFontColor(c.color)}
                                    />
                                ))}
                                <label
                                    className="relative grid place-items-center w-9 h-9 [@media(pointer:coarse)]:w-11 [@media(pointer:coarse)]:h-11 rounded-input cursor-pointer hover:bg-paper2 focus-within:outline focus-within:outline-2 focus-within:outline-[color:var(--color-focus)] transition-colors"
                                    title="Custom color"
                                >
                                    <span
                                        aria-hidden="true"
                                        className={`grid place-items-center w-6 h-6 rounded-full border border-dashed border-ink2 text-ink2 ${
                                            COLOR_PRESETS.some((c) => c.color === fontColor) ? '' : 'ring-2 ring-ink ring-offset-2 ring-offset-paper3'}`}
                                        style={COLOR_PRESETS.some((c) => c.color === fontColor) ? undefined : { backgroundColor: fontColor }}
                                    >
                                        {COLOR_PRESETS.some((c) => c.color === fontColor) && <Plus size={12} />}
                                    </span>
                                    <span className="sr-only">Custom text color</span>
                                    <input type="color" value={fontColor} onChange={(e) => setFontColor(e.target.value)} className="absolute inset-0 opacity-0 cursor-pointer" />
                                </label>
                            </div>
                        </div>

                        {/* Highlight Color (new) */}
                        <div role="group" aria-labelledby={`${uid}-highlight`}>
                            <p id={`${uid}-highlight`} className="text-xs font-medium text-ink2 mb-1">Highlighted word</p>
                            <div className="flex flex-wrap items-center gap-0.5 -ml-1.5">
                                {HIGHLIGHT_PRESETS.map((c) => (
                                    <Swatch
                                        key={c.color}
                                        color={c.color}
                                        label={c.label}
                                        selected={highlightColor === c.color}
                                        onClick={() => setHighlightColor(c.color)}
                                    />
                                ))}
                            </div>
                        </div>

                        {/* Border / Outline */}
                        <div className="pt-4 border-t border-rule space-y-3">
                            <ColorWell
                                label="Outline"
                                value={borderColor}
                                onChange={(e) => setBorderColor(e.target.value)}
                            />
                            <Slider
                                label="Outline width"
                                valueText={borderWidth > 0 ? `${borderWidth} of 5` : 'None'}
                                min="0"
                                max="5"
                                value={borderWidth}
                                onChange={(e) => setBorderWidth(parseInt(e.target.value))}
                                minLabel="None"
                                maxLabel="Thick"
                            />
                        </div>

                        {/* Background Box */}
                        <div className="pt-4 border-t border-rule space-y-3">
                            <Switch
                                label="Background box"
                                checked={bgOpacity > 0}
                                onChange={(e) => setBgOpacity(e.target.checked ? 0.5 : 0)}
                            />
                            {bgOpacity > 0 && (
                                <div className="space-y-3 animate-fade">
                                    <ColorWell
                                        label="Box"
                                        value={bgColor}
                                        onChange={(e) => setBgColor(e.target.value)}
                                    />
                                    <Slider
                                        label="Box opacity"
                                        valueText={`${Math.round(bgOpacity * 100)}%`}
                                        min="10"
                                        max="100"
                                        value={Math.round(bgOpacity * 100)}
                                        onChange={(e) => setBgOpacity(parseInt(e.target.value) / 100)}
                                        minLabel="Transparent"
                                        maxLabel="Solid"
                                    />
                                </div>
                            )}
                        </div>
                    </Group>

                    {useRemotionPreview && (
                        <Group title="Words">
                            {/* Translate captions: text only, voice stays original */}
                            <div>
                                <label htmlFor={`${uid}-lang`} className="block text-xs font-medium text-ink2 mb-2">Translate captions to</label>
                                <div className="flex gap-2">
                                    <select
                                        id={`${uid}-lang`}
                                        value={translateLang}
                                        onChange={(e) => setTranslateLang(e.target.value)}
                                        className="input-field flex-1 min-w-0 cursor-pointer"
                                        disabled={translating}
                                        aria-describedby={`${uid}-lang-hint`}
                                    >
                                        <option value="">Choose a language…</option>
                                        {Object.entries(LANGUAGES).sort((a, b) => a[1].localeCompare(b[1])).map(([code, name]) => (
                                            <option key={code} value={code}>{name}</option>
                                        ))}
                                    </select>
                                    <button
                                        type="button"
                                        onClick={handleTranslate}
                                        disabled={!translateLang || translating}
                                        className="btn-ghost shrink-0 !px-3"
                                        title="Translate the caption text only — the voice stays as-is"
                                    >
                                        {translating ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <Languages size={16} aria-hidden="true" />}
                                        {translating ? 'Translating…' : 'Translate'}
                                    </button>
                                </div>
                                <p className="sr-only" aria-live="polite">{translating ? 'Translating the captions…' : ''}</p>
                                {translateError && (
                                    <p role="alert" className="text-danger text-xs mt-2 flex items-start gap-1.5">
                                        <AlertCircle size={14} className="shrink-0 mt-px" aria-hidden="true" /> {translateError}
                                    </p>
                                )}
                                <p id={`${uid}-lang-hint`} className="text-xs text-muted mt-2 leading-relaxed">
                                    Translates the text only — the spoken voice is unaffected. To dub the voice
                                    itself, use “Dub voice” instead.
                                </p>
                            </div>

                            {/* Editable Transcript (collapsible) */}
                            <div className="pt-3 border-t border-rule">
                                <button
                                    type="button"
                                    onClick={() => setShowTextEditor(!showTextEditor)}
                                    aria-expanded={showTextEditor}
                                    aria-controls={`${uid}-words`}
                                    className="w-full flex items-center justify-between gap-3 min-h-[36px] [@media(pointer:coarse)]:min-h-[44px] text-left rounded-input"
                                >
                                    <span className="text-xs font-medium text-ink">Edit the words</span>
                                    <span className="flex items-center gap-2">
                                        <span className="font-mono text-[11px] text-muted tabular-nums">{captions.length} words</span>
                                        <ChevronDown size={16} className={`text-muted transition-transform duration-200 ${showTextEditor ? 'rotate-180' : ''}`} aria-hidden="true" />
                                    </span>
                                </button>
                                <div id={`${uid}-words`}>
                                    {showTextEditor && (
                                        <>
                                            <label htmlFor={`${uid}-words-text`} className="sr-only">Caption text</label>
                                            <textarea
                                                id={`${uid}-words-text`}
                                                value={editableText}
                                                onChange={(e) => handleTextEdit(e.target.value)}
                                                rows={5}
                                                className="input-field mt-2 resize-none leading-relaxed animate-fade"
                                                placeholder="Edit subtitle text..."
                                            />
                                        </>
                                    )}
                                </div>
                            </div>
                        </Group>
                    )}

                    {/* Clips ship captioned by default, so the way
                        out has to be here — otherwise a user who
                        doesn't want captions is stuck with them. */}
                    {onRemove && (
                        <section aria-labelledby={`${uid}-remove`} className="rounded-card border border-rule2 p-4 space-y-3">
                            <h3 id={`${uid}-remove`} className="font-display text-sm text-ink">No captions</h3>
                            <p className="text-xs text-muted leading-relaxed">Clips come captioned by default. Take them off this clip if you don't want them.</p>
                            <button
                                type="button"
                                onClick={onRemove}
                                disabled={isProcessing}
                                className="btn-danger"
                            >
                                <Trash2 size={14} aria-hidden="true" />
                                Remove captions from this clip
                            </button>
                        </section>
                    )}
                </div>
            </div>
        </Modal>
    );
}

// A group of controls in a sunken well, named by an h3.
function Group({ title, children }) {
    const id = useId();
    return (
        <section aria-labelledby={id} className="tray p-4 space-y-4">
            <h3 id={id} className="font-display text-sm text-ink">{title}</h3>
            {children}
        </section>
    );
}

// A labelled range input with its value read out in mono beside the label.
function Slider({ label, valueText, minLabel, maxLabel, ...input }) {
    const id = useId();
    return (
        <div>
            <div className="flex items-baseline justify-between gap-3 mb-1">
                <label htmlFor={id} className="text-xs font-medium text-ink2">{label}</label>
                <output htmlFor={id} className="font-mono text-xs text-ink tabular-nums">{valueText}</output>
            </div>
            <input id={id} type="range" aria-valuetext={valueText} className="w-full h-7 cursor-pointer accent-ink" {...input} />
            {(minLabel || maxLabel) && (
                <div className="flex justify-between font-mono text-[11px] text-muted" aria-hidden="true">
                    <span>{minLabel}</span>
                    <span>{maxLabel}</span>
                </div>
            )}
        </div>
    );
}

// An on/off switch: a real checkbox (keyboard, screen readers) drawn as a slide.
function Switch({ label, checked, onChange }) {
    return (
        <label className="flex items-center justify-between gap-4 min-h-[36px] [@media(pointer:coarse)]:min-h-[44px] cursor-pointer">
            <span className="text-xs font-medium text-ink2">{label}</span>
            <span className="flex items-center gap-2 shrink-0">
                <span className="font-mono text-[11px] text-muted w-6 text-right" aria-hidden="true">{checked ? 'On' : 'Off'}</span>
                <input type="checkbox" role="switch" checked={checked} onChange={onChange} className="peer sr-only" />
                <span
                    aria-hidden="true"
                    className="relative w-10 h-6 rounded-[6px] border border-rule2 bg-paper2 transition-colors duration-200
                        peer-checked:bg-ink peer-checked:border-ink
                        peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-[color:var(--color-focus)]
                        after:content-[''] after:absolute after:top-[3px] after:left-[3px] after:w-4 after:h-4 after:rounded-[4px] after:bg-ink2
                        after:transition-transform after:duration-200 peer-checked:after:translate-x-4 peer-checked:after:bg-paper2"
                />
            </span>
        </label>
    );
}

// One preset colour of the caption itself (the value is burned into the video).
function Swatch({ color, label, selected, onClick }) {
    return (
        <button
            type="button"
            onClick={onClick}
            aria-pressed={selected}
            aria-label={label}
            title={label}
            className="grid place-items-center w-9 h-9 [@media(pointer:coarse)]:w-11 [@media(pointer:coarse)]:h-11 rounded-input hover:bg-paper2 transition-colors"
        >
            <span
                aria-hidden="true"
                className={`block w-6 h-6 rounded-full border border-rule2 ${selected ? 'ring-2 ring-ink ring-offset-2 ring-offset-paper3' : ''}`}
                style={{ backgroundColor: color }}
            />
        </button>
    );
}

// A colour picker shown as a labelled well with its hex value.
function ColorWell({ label, value, onChange }) {
    return (
        <label className="relative flex items-center gap-3 cursor-pointer rounded-input focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-[color:var(--color-focus)]">
            <span
                aria-hidden="true"
                className="w-9 h-9 [@media(pointer:coarse)]:w-11 [@media(pointer:coarse)]:h-11 rounded-input border border-rule2 shrink-0"
                style={{ backgroundColor: value }}
            />
            <span className="text-xs font-medium text-ink2">{label} color</span>
            <span className="ml-auto font-mono text-[11px] text-muted" aria-hidden="true">{value}</span>
            <input type="color" value={value} onChange={onChange} className="absolute inset-0 w-full h-full opacity-0 cursor-pointer" />
        </label>
    );
}
