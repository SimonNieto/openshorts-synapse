import { useEffect, useState } from 'react';
import { loadNicheHistory } from '../lib/nicheHistory';

/**
 * Inline niche field + one-click history chips. Lives directly inside the
 * screens that need a niche (scheduling, posting, the pre-download prompt) so
 * picking one is part of the same screen rather than an extra modal step.
 */
export default function NichePicker({ value, onChange, onEnter, autoFocus = false }) {
    const [history, setHistory] = useState([]);
    useEffect(() => { setHistory(loadNicheHistory()); }, []);

    return (
        <div className="space-y-2.5">
            <input
                type="text"
                autoFocus={autoFocus}
                value={value}
                onChange={(e) => onChange(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && onEnter) onEnter(); }}
                className="input-field w-full"
                aria-label="Channel niche"
                placeholder="Niche, e.g. Joe Rogan podcast clips"
            />
            {history.length > 0 && (
                <div role="group" aria-label="Niches used before" className="flex flex-wrap gap-1.5">
                    {history.map((n) => {
                        const active = n.toLowerCase() === (value || '').trim().toLowerCase();
                        return (
                            <button
                                key={n}
                                type="button"
                                onClick={() => onChange(n)}
                                aria-pressed={active}
                                className={`min-h-[32px] [@media(pointer:coarse)]:min-h-[44px] px-2.5 py-1 rounded-input border text-xs transition-colors ${active
                                    ? 'bg-vermilionsoft text-ink border-vermilion'
                                    : 'bg-paper3 text-ink2 border-transparent hover:border-rule2 hover:text-ink'}`}
                            >
                                {n}
                            </button>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
