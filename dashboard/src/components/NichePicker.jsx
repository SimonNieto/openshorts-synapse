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
        <div className="space-y-2">
            <input
                type="text"
                autoFocus={autoFocus}
                value={value}
                onChange={(e) => onChange(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && onEnter) onEnter(); }}
                className="input-field w-full"
                placeholder="niche, e.g. Joe Rogan podcast clips"
            />
            {history.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                    {history.map((n) => {
                        const active = n.toLowerCase() === (value || '').trim().toLowerCase();
                        return (
                            <button
                                key={n}
                                type="button"
                                onClick={() => onChange(n)}
                                className={`readout px-2 py-1 rounded-full transition-colors ${active
                                    ? 'bg-brass/20 text-brass border border-brass/50'
                                    : 'bg-paper3 hover:bg-paper2 text-ink2 border border-transparent'}`}
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
