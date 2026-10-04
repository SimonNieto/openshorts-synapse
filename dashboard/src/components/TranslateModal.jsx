import React, { useState, useId } from 'react';
import { Loader2, Languages, AlertCircle, ChevronDown } from 'lucide-react';
import Modal from './ui/Modal';

// Shared with SubtitleModal and ReworkerTab (their language pickers).
// eslint-disable-next-line react-refresh/only-export-components
export const LANGUAGES = {
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "pl": "Polish",
    "hi": "Hindi",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "ar": "Arabic",
    "ru": "Russian",
    "tr": "Turkish",
    "nl": "Dutch",
    "sv": "Swedish",
    "id": "Indonesian",
    "fil": "Filipino",
    "ms": "Malay",
    "vi": "Vietnamese",
    "th": "Thai",
    "uk": "Ukrainian",
    "el": "Greek",
    "cs": "Czech",
    "fi": "Finnish",
    "ro": "Romanian",
    "da": "Danish",
    "bg": "Bulgarian",
    "hr": "Croatian",
    "sk": "Slovak",
    "ta": "Tamil",
    "en": "English",
};

export default function TranslateModal({ isOpen, onClose, onTranslate, isProcessing, videoUrl, hasApiKey }) {
    const [targetLanguage, setTargetLanguage] = useState('es');
    // Presentation only: ties the language label to its select.
    const uid = useId();
    const languageId = `${uid}-language`;
    const noteId = `${uid}-note`;

    if (!isOpen) return null;

    const handleSubmit = () => {
        console.log('[TranslateModal] handleSubmit called, targetLanguage:', targetLanguage);
        onTranslate({ targetLanguage });
    };

    return (
        <Modal
            isOpen={isOpen}
            onClose={isProcessing ? undefined : onClose}
            eyebrow="AI voice · ElevenLabs"
            title="Dub voice"
            size="md"
            footer={
                <div className="flex flex-col-reverse sm:flex-row gap-2 sm:gap-3">
                    <button
                        type="button"
                        onClick={onClose}
                        disabled={isProcessing}
                        className="btn-ghost sm:flex-1"
                    >
                        Cancel
                    </button>
                    <button
                        type="button"
                        onClick={handleSubmit}
                        disabled={isProcessing || !hasApiKey}
                        className="btn-accent sm:flex-1"
                    >
                        {isProcessing ? (
                            <>
                                <Loader2 size={16} className="animate-spin" aria-hidden="true" />
                                Dubbing…
                            </>
                        ) : (
                            <>
                                <Languages size={16} aria-hidden="true" />
                                Dub voice
                            </>
                        )}
                    </button>
                </div>
            }
        >
            <p className="text-sm text-muted leading-relaxed mb-5">
                Translates the speech of this clip and re-voices it in another language with AI.
            </p>

            {!hasApiKey && (
                <div className="mb-5 flex items-start gap-2.5 rounded-input border border-warn/30 bg-warn/10 px-3 py-2.5 text-[13px] leading-relaxed text-ink2">
                    <AlertCircle size={15} className="mt-0.5 shrink-0 text-warn" aria-hidden="true" />
                    <p><span className="font-medium text-ink">ElevenLabs key missing.</span> Add your ElevenLabs API key in Settings first.</p>
                </div>
            )}

            {/* Preview: the clip as it is now, on black, in a hairline frame */}
            <figure className="mb-5">
                <div className="h-56 sm:h-64 flex items-center justify-center bg-black border border-rule2 rounded-input overflow-hidden">
                    <video
                        src={videoUrl}
                        className="h-full w-auto max-w-full object-contain"
                        aria-label="Clip preview"
                        muted
                        playsInline
                    />
                </div>
                <figcaption className="readout mt-2 text-center">Current version</figcaption>
            </figure>

            {/* Language Selection */}
            <div className="mb-5">
                <label htmlFor={languageId} className="readout text-ink2 block mb-2">
                    Target language
                </label>
                <div className="relative">
                    <select
                        id={languageId}
                        aria-describedby={noteId}
                        value={targetLanguage}
                        onChange={(e) => setTargetLanguage(e.target.value)}
                        className="input-field appearance-none cursor-pointer pr-10"
                        disabled={isProcessing}
                    >
                        {Object.entries(LANGUAGES).sort((a, b) => a[1].localeCompare(b[1])).map(([code, name]) => (
                            <option key={code} value={code}>
                                {name}
                            </option>
                        ))}
                    </select>
                    <ChevronDown
                        size={16}
                        className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-muted"
                        aria-hidden="true"
                    />
                </div>
            </div>

            {/* Info */}
            <div id={noteId} className="space-y-2 text-xs text-muted leading-relaxed">
                <p>
                    The audio will be dubbed with AI-generated voice in the selected language, matching the original speaker's characteristics.
                </p>

                {/* AI Act art. 50: we mark the file, the person publishing it is the
                    one who owes the audience the disclosure. Saying so here is the
                    only place they will read it. */}
                <p>
                    The dubbed file is tagged as AI-generated content. When you publish it, disclose that the voice is synthetic.
                </p>
            </div>

            {/* Processing State */}
            <div aria-live="polite">
                {isProcessing && (
                    <div className="tray mt-5 p-3 flex items-center gap-3">
                        <Loader2 size={18} className="shrink-0 text-ink animate-spin" aria-hidden="true" />
                        <div>
                            <p className="text-sm text-ink font-medium">Dubbing audio…</p>
                            <p className="text-xs text-muted">This may take a few minutes.</p>
                        </div>
                    </div>
                )}
            </div>
        </Modal>
    );
}
