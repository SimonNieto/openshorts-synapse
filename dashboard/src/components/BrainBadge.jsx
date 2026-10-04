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

    return (
        <div className="tray px-3.5 py-3 flex items-start gap-3 min-w-0">
            <span
                aria-hidden="true"
                className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border ${isClaude || isGemini ? 'border-rule2 text-ink' : 'border-rule text-muted'}`}
            >
                <Brain size={15} />
            </span>
            <div className="min-w-0">
                <p className="readout">Thinking now</p>
                <p className="mt-0.5 text-sm font-medium text-ink break-words">
                    {isClaude ? `${who} is working` : who}
                </p>
                {stage && <p className="text-sm text-ink2 leading-snug break-words">{stage}…</p>}
            </div>
        </div>
    );
}
