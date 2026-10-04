import React, { useState, useEffect } from 'react';
import { Eye, EyeOff, Check, ExternalLink } from 'lucide-react';

// The Gemini key, as one section of the Settings page: heading and purpose
// above, the labelled field in a card below (same anatomy as every other
// Settings section in App.jsx).
export default function KeyInput({ onKeySet, savedKey }) {
    const [key, setKey] = useState(savedKey || '');
    const [isVisible, setIsVisible] = useState(false);
    const [isSaved, setIsSaved] = useState(!!savedKey);

    useEffect(() => {
        if (savedKey) setKey(savedKey);
    }, [savedKey]);

    const handleSave = () => {
        if (key.trim().length > 0) {
            onKeySet(key);
            setIsSaved(true);
        }
    };

    return (
        <section aria-labelledby="settings-gemini" className="space-y-4 animate-fade">
            <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                    <h2 id="settings-gemini" className="font-display text-lg text-ink">Gemini API key</h2>
                    <p id="settings-gemini-help" className="mt-1 text-sm text-muted leading-relaxed">
                        Finds the best moments in your videos and writes their titles.
                    </p>
                </div>
                {isSaved && (
                    <span className="badge-ok shrink-0 mt-1">
                        <Check size={11} aria-hidden="true" /> Saved
                    </span>
                )}
            </div>

            <div className="card p-4 sm:p-6">
                <label htmlFor="settings-gemini-key" className="block text-sm font-medium text-ink2 mb-2">
                    API key
                </label>
                <div className="flex flex-col sm:flex-row gap-2">
                    <div className="relative sm:flex-1">
                        <input
                            id="settings-gemini-key"
                            type={isVisible ? "text" : "password"}
                            value={key}
                            onChange={(e) => {
                                setKey(e.target.value);
                                setIsSaved(false);
                            }}
                            placeholder="AIzaSy..."
                            autoComplete="off"
                            spellCheck={false}
                            aria-describedby="settings-gemini-help settings-gemini-note"
                            className="input-field pr-12 font-mono"
                        />
                        <button
                            type="button"
                            onClick={() => setIsVisible(!isVisible)}
                            aria-label={isVisible ? 'Hide key' : 'Show key'}
                            aria-pressed={isVisible}
                            className="absolute right-1 top-1/2 -translate-y-1/2 w-10 h-10 flex items-center justify-center rounded-input text-muted hover:text-ink hover:bg-paper3 transition-colors"
                        >
                            {isVisible ? <EyeOff size={17} aria-hidden="true" /> : <Eye size={17} aria-hidden="true" />}
                        </button>
                    </div>
                    {isSaved ? (
                        <button
                            type="button"
                            disabled
                            className="inline-flex items-center justify-center gap-1.5 px-4 py-2 min-h-[44px] sm:min-h-0 rounded-input border border-rule text-sm text-ok cursor-default"
                        >
                            <Check size={14} aria-hidden="true" /> Saved
                        </button>
                    ) : (
                        <button
                            type="button"
                            onClick={handleSave}
                            disabled={!key}
                            className="btn-primary px-5 py-2 text-sm"
                        >
                            Save key
                        </button>
                    )}
                </div>
                <p id="settings-gemini-note" className="mt-3 text-xs text-muted flex flex-wrap items-center gap-x-3 gap-y-1">
                    <span>Kept in this browser for convenience.</span>
                    <a
                        href="https://aistudio.google.com/app/apikey"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-cobalt underline underline-offset-2 hover:text-ink transition-colors"
                    >
                        Get a free Gemini key
                        <ExternalLink size={12} aria-hidden="true" />
                        <span className="sr-only">(opens in a new tab)</span>
                    </a>
                </p>
                <span className="sr-only" aria-live="polite">{isSaved ? 'Gemini key saved.' : ''}</span>
            </div>
        </section>
    );
}
