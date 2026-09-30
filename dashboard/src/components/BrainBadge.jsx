import React from 'react';
import { Brain } from 'lucide-react';

// ai_brain.say() prints one line per thinking stage: "🧠 [<who>] <stage>".
const BRAIN_LINE = /🧠 \[([^\]]+)\]\s*(.*)$/u;

/**
 * Who is thinking right now in the job (Claude, Gemini as its fallback,
 * Whisper for the transcription), read from the latest "🧠 [...]" log line.
 * Nothing before the first one.
 */
export default function BrainBadge({ logs }) {
    let who = null;
    let stage = '';
    for (let i = (logs?.length || 0) - 1; i >= 0; i--) {
        const m = BRAIN_LINE.exec(logs[i] || '');
        if (m) {
            who = m[1];
            stage = m[2];
            break;
        }
    }
    if (!who) return null;

    const name = who.toLowerCase();
    const isClaude = name.startsWith('claude');
    const isGemini = name.startsWith('gemini');
    const tone = isClaude
        ? 'border-brass/40 bg-brass/10 text-ink'
        : isGemini
            ? 'border-danger/40 bg-danger/5 text-ink'
            : 'border-rule bg-paper2 text-ink2';

    return (
        <div className={`mb-3 sm:mb-4 rounded-card border px-3 py-2.5 flex items-start gap-2.5 min-w-0 ${tone}`}>
            <Brain size={16} className={`shrink-0 mt-px animate-pulse ${isClaude ? 'text-brass' : isGemini ? 'text-danger' : 'text-muted'}`} />
            <div className="min-w-0 text-xs leading-snug">
                <p className="font-medium break-words">
                    {isClaude ? `${who} is working` : who}
                </p>
                {stage && <p className="text-ink2 break-words">{stage}…</p>}
            </div>
        </div>
    );
}
