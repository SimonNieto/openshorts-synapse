import { useEffect, useState } from 'react';
import Modal from './ui/Modal';
import NichePicker from './NichePicker';

/**
 * Asked before EVERY action that uses a niche (hashtag download bundling,
 * copy regeneration) — never silently reused, so working across several
 * niches in the same session never risks the wrong one sticking from a
 * previous action. History chips make re-picking a regular one a click.
 *
 * Props:
 *  - isOpen / onClose
 *  - defaultValue: prefilled text (usually the last one used)
 *  - message: body copy explaining what the niche is used for
 *  - onConfirm(niche): called with the trimmed niche text
 *  - onSkip: optional — omit to hide the "skip" button
 */
export default function NichePromptModal({ isOpen, onClose, defaultValue = '', message, onConfirm, onSkip }) {
    const [value, setValue] = useState(defaultValue);

    useEffect(() => {
        if (isOpen) setValue(defaultValue);
    }, [isOpen, defaultValue]);

    const confirm = () => {
        if (value.trim()) onConfirm(value.trim());
    };

    return (
        <Modal isOpen={isOpen} onClose={onClose} size="sm" eyebrow="Hashtags" title="What's this channel's niche?">
            <div className="space-y-4">
                {message && <p className="text-sm text-ink2 leading-relaxed">{message}</p>}
                <NichePicker value={value} onChange={setValue} onEnter={confirm} autoFocus />
                <div className="flex flex-wrap gap-2 justify-end pt-1">
                    {onSkip && (
                        <button type="button" onClick={onSkip} className="btn-ghost px-4 py-2 text-sm">
                            Skip
                        </button>
                    )}
                    <button
                        type="button"
                        onClick={confirm}
                        disabled={!value.trim()}
                        className="btn-accent px-5 py-2 text-sm"
                    >
                        Confirm
                    </button>
                </div>
            </div>
        </Modal>
    );
}
