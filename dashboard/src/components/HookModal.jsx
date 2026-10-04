import React, { useState, useId } from 'react';
import { Loader2, AlertTriangle, Info, Lightbulb, Trash2 } from 'lucide-react';
import RemotionPreview from './RemotionPreview';
import Modal from './ui/Modal';
import SegmentedControl from './ui/SegmentedControl';

const ENTRANCE_OPTIONS = [
    { value: 'spring', label: 'Bounce' },
    { value: 'fade', label: 'Fade' },
    { value: 'slide-up', label: 'Slide up' },
    { value: 'none', label: 'None' },
];

// Must mirror hooks.py HOOK_STYLES.
const HOOK_STYLES = [
    { value: 'classic', label: 'Classic', box: 'rgba(255,255,255,0.94)', text: '#000' },
    { value: 'dark', label: 'Dark', box: 'rgba(18,18,20,0.92)', text: '#fff' },
    { value: 'yellow', label: 'Yellow', box: 'rgba(255,214,0,0.96)', text: '#000' },
    { value: 'red', label: 'Red', box: 'rgba(220,38,38,0.96)', text: '#fff' },
    { value: 'outline', label: 'Outline', box: 'transparent', text: '#fff', outline: true },
    { value: 'outline_yellow', label: 'Outline+', box: 'transparent', text: '#FFD600', outline: true },
    { value: 'bold', label: 'Bold', box: 'transparent', text: '#fff', outline: true },
    { value: 'docline', label: 'Doc line', box: 'transparent', text: '#fff' },
];

const POSITION_OPTIONS = [
    { value: 'top', label: 'Top' },
    { value: 'center', label: 'Center' },
    { value: 'bottom', label: 'Bottom' },
];

const SIZE_OPTIONS = [
    { value: 'S', label: 'Small' },
    { value: 'M', label: 'Medium' },
    { value: 'L', label: 'Large' },
];

// Last-used hook settings, restored on the next open (style always reset to
// classic otherwise, which users read as the picker being broken).
function loadHookPrefs() {
    try { return JSON.parse(localStorage.getItem('os_hook_prefs')) || {}; } catch { return {}; }
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

// A labelled option set: the label names the radiogroup inside it.
function Field({ label, children }) {
    const id = useId();
    return (
        <div role="group" aria-labelledby={id}>
            <p id={id} className="text-xs font-medium text-ink2 mb-2">{label}</p>
            {children}
        </div>
    );
}

export default function HookModal({ isOpen, onClose, onGenerate, onRemove, isProcessing, videoUrl, initialText, durationInSeconds, existingSubtitles, hasCaptions, serverRender, burnedHook }) {
    const prefs = loadHookPrefs();
    const [text, setText] = useState(initialText || 'POV: You are using the viral hook feature');
    const [position, setPosition] = useState(prefs.position || 'top');
    const [size, setSize] = useState(prefs.size || 'M');
    const [style, setStyle] = useState(prefs.style || 'classic');
    const [entranceAnimation, setEntranceAnimation] = useState(prefs.entranceAnimation || 'spring');
    const [displayDuration, setDisplayDuration] = useState(5);
    const uid = useId();

    if (!isOpen) return null;

    // Build hook config for Remotion preview
    const hookConfig = {
        text: text || 'Enter your text...',
        position,
        size,
        style,
        entranceAnimation,
        displayDurationSec: displayDuration,
    };

    const useRemotionPreview = !!videoUrl;

    // Fallback preview logic (same as original)
    const getPositionClass = () => {
        switch (position) {
            case 'center': return 'items-center justify-center';
            case 'bottom': return 'items-center justify-end pb-[20%]';
            case 'top': default: return 'items-center justify-start pt-[20%]';
        }
    };

    const getSizeStyle = () => {
        switch (size) {
            case 'S': return { fontSize: '14px', maxWidth: '80%' };
            case 'L': return { fontSize: '24px', maxWidth: '95%' };
            case 'M': default: return { fontSize: '18px', maxWidth: '90%' };
        }
    };

    const footer = (
        <div className="flex flex-wrap items-center justify-end gap-2">
            <p className="sr-only" aria-live="polite">{isProcessing ? 'Adding the hook to the clip…' : ''}</p>
            <button type="button" onClick={onClose} className="btn-ghost flex-1 sm:flex-none">
                Cancel
            </button>
            <button
                type="button"
                onClick={() => {
                    try {
                        localStorage.setItem('os_hook_prefs', JSON.stringify({
                            style, position, size, entranceAnimation,
                        }));
                    } catch { /* ignore */ }
                    onGenerate({
                        text, position, size, style,
                        // Remotion data
                        remotion: hookConfig,
                    });
                }}
                disabled={isProcessing || !text.trim()}
                className="btn-accent flex-[2] sm:flex-none sm:min-w-[11rem]"
            >
                {isProcessing && <Loader2 size={16} className="animate-spin" aria-hidden="true" />}
                {isProcessing ? 'Adding hook…' : 'Add hook'}
            </button>
        </div>
    );

    return (
        <Modal isOpen={isOpen} onClose={onClose} size="xl" title="Add a hook" footer={footer}>
            <div className="grid gap-6 md:grid-cols-[minmax(0,1fr)_20rem] lg:grid-cols-[minmax(0,1fr)_22rem] md:items-start">
                {/* Preview: the clip on true black, held in place while the controls scroll */}
                <figure className="md:sticky md:top-0 flex flex-col items-center gap-2 min-w-0">
                    <div className="relative flex flex-col items-center justify-center bg-black border border-rule2 rounded-card overflow-hidden aspect-[9/16] h-[50vh] sm:h-[min(600px,62vh)] max-w-full">
                        {useRemotionPreview ? (
                            <RemotionPreview
                                videoUrl={videoUrl}
                                durationInSeconds={durationInSeconds || 30}
                                hook={hookConfig}
                                subtitles={existingSubtitles || null}
                            />
                        ) : (
                            <>
                                <video src={videoUrl} className="w-full h-full object-contain opacity-50" muted playsInline />
                                <div className={`absolute w-full px-8 text-center transition-all duration-300 pointer-events-none flex flex-col h-full ${getPositionClass()}`}>
                                    <div
                                        className="text-black font-bold px-3 py-2 rounded-xl shadow-2xl text-center whitespace-pre-wrap transition-all duration-200"
                                        style={{
                                            ...getSizeStyle(),
                                            backgroundColor: 'rgba(255, 255, 255, 0.82)',
                                            fontFamily: 'Noto Serif, serif',
                                            boxShadow: '0 4px 15px rgba(0,0,0,0.5)',
                                            paddingTop: '10px',
                                            paddingBottom: '10px',
                                            paddingLeft: '12px',
                                            paddingRight: '12px'
                                        }}
                                    >
                                        {text || "Enter your text..."}
                                    </div>
                                </div>
                            </>
                        )}
                    </div>
                    <figcaption className="readout">Preview · 9:16</figcaption>
                </figure>

                {/* Controls */}
                <div className="space-y-4 min-w-0">
                    <Group title="Text">
                        <div>
                            <div className="flex items-baseline justify-between gap-3 mb-2">
                                <label htmlFor={`${uid}-text`} className="text-xs font-medium text-ink2">Hook line</label>
                                <span className="font-mono text-[11px] text-muted tabular-nums" aria-hidden="true">{text.length} chars</span>
                            </div>
                            <textarea
                                id={`${uid}-text`}
                                value={text}
                                onChange={(e) => setText(e.target.value)}
                                rows={4}
                                aria-describedby={`${uid}-tip`}
                                className="input-field resize-none"
                                style={{ fontFamily: 'Noto Serif, serif' }}
                                placeholder="Enter text that will stop the scroll..."
                            />
                            <p id={`${uid}-tip`} className="mt-2 flex gap-2 text-xs text-muted leading-relaxed">
                                <Lightbulb size={14} className="shrink-0 mt-px" aria-hidden="true" />
                                <span>Keep it short and punchy. Opening with "POV:" or a specific question works best for retention.</span>
                            </p>
                        </div>
                    </Group>

                    <Group title="Look">
                        <div role="radiogroup" aria-labelledby={`${uid}-style`}>
                            <p id={`${uid}-style`} className="text-xs font-medium text-ink2 mb-2">Style</p>
                            <div className="grid grid-cols-4 gap-1.5">
                                {HOOK_STYLES.map((s) => {
                                    const active = style === s.value;
                                    return (
                                        <button
                                            key={s.value}
                                            type="button"
                                            role="radio"
                                            aria-checked={active}
                                            onClick={() => setStyle(s.value)}
                                            className={`flex flex-col items-stretch gap-1.5 p-1.5 rounded-input border transition-colors duration-200
                                                ${active ? 'border-ink bg-paper2 ring-1 ring-ink' : 'border-rule2 bg-paper2 hover:border-ink'}`}
                                        >
                                            {/* the look itself, drawn on true black like the clip */}
                                            <span className="flex items-center justify-center h-10 rounded-[5px] bg-black" aria-hidden="true">
                                                <span
                                                    className="rounded-[3px] px-1.5 py-0.5 text-sm font-bold leading-none"
                                                    style={{
                                                        backgroundColor: s.box,
                                                        color: s.text,
                                                        fontFamily: 'Noto Serif, serif',
                                                        textShadow: s.outline ? '-1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000' : 'none',
                                                    }}
                                                >Aa</span>
                                            </span>
                                            <span className={`text-[12px] leading-tight text-center ${active ? 'text-ink font-semibold' : 'text-ink2'}`}>{s.label}</span>
                                        </button>
                                    );
                                })}
                            </div>
                        </div>

                        <Field label="Size">
                            <SegmentedControl
                                options={SIZE_OPTIONS}
                                value={size}
                                onChange={setSize}
                                size="sm"
                            />
                        </Field>

                        <Field label="Position">
                            <SegmentedControl
                                options={POSITION_OPTIONS}
                                value={position}
                                onChange={setPosition}
                                size="sm"
                            />
                            {position === 'bottom' && hasCaptions && (
                                <p className="mt-2 flex gap-2 text-xs text-warn leading-relaxed">
                                    <AlertTriangle size={14} className="shrink-0 mt-px" aria-hidden="true" />
                                    <span>This clip has captions near the bottom — the hook may overlap them (and TikTok's UI). Top is the safe zone.</span>
                                </p>
                            )}
                        </Field>
                    </Group>

                    <Group title="Timing">
                        <Field label="Entrance">
                            <SegmentedControl
                                options={ENTRANCE_OPTIONS}
                                value={entranceAnimation}
                                onChange={setEntranceAnimation}
                                columns={2}
                                size="sm"
                            />
                            {serverRender && (
                                <p className="mt-2 flex gap-2 text-xs text-muted leading-relaxed">
                                    <Info size={14} className="shrink-0 mt-px" aria-hidden="true" />
                                    <span>This clip re-renders on the server, where the hook is static — the entrance animation won't apply.</span>
                                </p>
                            )}
                        </Field>

                        <div>
                            <div className="flex items-baseline justify-between gap-3 mb-1">
                                <label htmlFor={`${uid}-duration`} className="text-xs font-medium text-ink2">On screen for</label>
                                <output htmlFor={`${uid}-duration`} className="font-mono text-xs text-ink tabular-nums">{displayDuration} s</output>
                            </div>
                            <input
                                id={`${uid}-duration`}
                                type="range"
                                min="2"
                                max="15"
                                value={displayDuration}
                                onChange={(e) => setDisplayDuration(parseInt(e.target.value))}
                                aria-valuetext={`${displayDuration} seconds`}
                                className="w-full h-7 cursor-pointer accent-ink"
                            />
                            <div className="flex justify-between font-mono text-[11px] text-muted" aria-hidden="true">
                                <span>2 s</span>
                                <span>15 s</span>
                            </div>
                        </div>
                    </Group>

                    {burnedHook && (
                        <section aria-labelledby={`${uid}-burned`} className="rounded-card border border-rule2 p-4 space-y-3">
                            <h3 id={`${uid}-burned`} className="font-display text-sm text-ink">Hook already in this clip</h3>
                            <p className="text-xs text-ink2 leading-relaxed">
                                This clip has a hook burned in (“{burnedHook}”). Adding a new one replaces it.
                            </p>
                            {onRemove && (
                                <button
                                    type="button"
                                    onClick={onRemove}
                                    disabled={isProcessing}
                                    className="btn-danger"
                                >
                                    <Trash2 size={14} aria-hidden="true" />
                                    Remove hook from clip
                                </button>
                            )}
                        </section>
                    )}
                </div>
            </div>
        </Modal>
    );
}
