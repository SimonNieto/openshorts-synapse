import React, { useState, useId } from 'react';
import { Zap, Video, Instagram, Youtube } from 'lucide-react';
import { loadNicheHistory, profileForNiche } from '../lib/nicheHistory';

const PLATFORMS = [
    { id: 'tiktok', label: 'TikTok', icon: <Video size={13} aria-hidden="true" /> },
    { id: 'instagram', label: 'Instagram', icon: <Instagram size={13} aria-hidden="true" /> },
    { id: 'youtube', label: 'YouTube', icon: <Youtube size={13} aria-hidden="true" /> },
];

// Toggle chips: rectangles, monochrome. Selected = white ink fill, like the
// shared SegmentedControl, so "on" reads the same everywhere in the app.
const chip = (active) => `inline-flex items-center gap-1.5 min-h-[32px] [@media(pointer:coarse)]:min-h-[44px] px-2.5 py-1.5 rounded-input border text-xs transition-colors ${active
    ? 'bg-ink text-paper2 border-ink'
    : 'bg-paper3 text-ink2 border-rule hover:text-ink hover:border-rule2'}`;

const GROUP_LABEL = 'readout text-ink2 block mb-2';

/**
 * "Publish the 3 best clips automatically": when the job ends, the server
 * schedules its 3 highest-scored clips on Upload-Post, in the account's next
 * free 8h / 12h / 20h slots — never two posts at the same time on the same
 * account and platform.
 */
export default function AutoPublishOption({ value, onChange, profiles = [], defaultProfile = '', available }) {
    const [history] = useState(loadNicheHistory);
    const set = (patch) => onChange({ ...value, ...patch });
    const profileNames = profiles.map((p) => p.username).filter(Boolean);
    const activeProfile = value.profile || defaultProfile || profileNames[0] || '';

    const togglePlatform = (id) => {
        const next = value.platforms.includes(id) ? value.platforms.filter((p) => p !== id) : [...value.platforms, id];
        if (next.length) set({ platforms: next });
    };

    // Presentation only: ids tying the labels to their controls.
    const uid = useId();
    const checkboxId = `${uid}-enabled`;
    const descId = `${uid}-desc`;
    const accountId = `${uid}-account`;
    const nicheId = `${uid}-niche`;
    const platformsId = `${uid}-platforms`;
    const isOn = value.enabled && available;

    return (
        <div className={`mt-4 rounded-input border transition-colors ${isOn ? 'border-rule2 bg-paper3' : 'border-rule'}`}>
            <div className={`flex items-start gap-3 p-3 ${available ? '' : 'opacity-60'}`}>
                <input
                    id={checkboxId}
                    type="checkbox"
                    checked={value.enabled && available}
                    disabled={!available}
                    onChange={(e) => set({ enabled: e.target.checked })}
                    aria-describedby={descId}
                    className={`mt-0.5 w-4 h-4 shrink-0 accent-[var(--color-accent)] ${available ? 'cursor-pointer' : 'cursor-not-allowed'}`}
                />
                <div className="min-w-0">
                    <label
                        htmlFor={checkboxId}
                        className={`text-sm font-medium text-ink flex items-center gap-1.5 select-none ${available ? 'cursor-pointer' : 'cursor-not-allowed'}`}
                    >
                        <Zap size={14} className="shrink-0 text-muted" aria-hidden="true" />
                        Publish the 3 best clips automatically
                    </label>
                    <p id={descId} className="text-xs text-muted mt-1 leading-relaxed">
                        {available
                            ? 'Highest viral scores, scheduled on Upload-Post in the next free 8h · 12h · 20h slots of the account — after what is already planned, never two posts at the same time.'
                            : 'Set your Upload-Post key in Settings to use this.'}
                    </p>
                </div>
            </div>

            {value.enabled && available && (
                <div className="px-3 pb-3 pt-3 space-y-4 border-t border-rule animate-fade">
                    {profileNames.length > 1 && (
                        <div role="group" aria-labelledby={accountId}>
                            <p id={accountId} className={GROUP_LABEL}>Account</p>
                            <div className="flex flex-wrap gap-1.5">
                                {profileNames.map((name) => (
                                    <button
                                        key={name}
                                        type="button"
                                        onClick={() => set({ profile: name })}
                                        aria-pressed={name === activeProfile}
                                        className={chip(name === activeProfile)}
                                    >
                                        {name}
                                    </button>
                                ))}
                            </div>
                        </div>
                    )}
                    <div>
                        <label htmlFor={nicheId} className={GROUP_LABEL}>Niche and hashtags</label>
                        <input
                            id={nicheId}
                            type="text"
                            value={value.niche}
                            onChange={(e) => set({ niche: e.target.value })}
                            placeholder="Empty = the AI's guess for this video"
                            className="input-field text-sm"
                        />
                        {history.length > 0 && (
                            <div className="flex flex-wrap gap-1.5 mt-2" role="group" aria-label="Recent niches">
                                {history.map((n) => (
                                    <button
                                        key={n}
                                        type="button"
                                        onClick={() => {
                                            const same = value.niche.toLowerCase() === n.toLowerCase();
                                            const known = profileForNiche(n);
                                            set({ niche: same ? '' : n, ...(!same && known && profileNames.includes(known) ? { profile: known } : {}) });
                                        }}
                                        aria-pressed={value.niche.toLowerCase() === n.toLowerCase()}
                                        className={chip(value.niche.toLowerCase() === n.toLowerCase())}
                                    >
                                        {n}
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>
                    <div role="group" aria-labelledby={platformsId}>
                        <p id={platformsId} className={GROUP_LABEL}>Platforms</p>
                        <div className="flex flex-wrap gap-1.5">
                            {PLATFORMS.map((p) => (
                                <button
                                    key={p.id}
                                    type="button"
                                    onClick={() => togglePlatform(p.id)}
                                    aria-pressed={value.platforms.includes(p.id)}
                                    className={chip(value.platforms.includes(p.id))}
                                >
                                    {p.icon} {p.label}
                                </button>
                            ))}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
