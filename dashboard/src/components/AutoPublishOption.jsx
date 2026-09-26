import React, { useState } from 'react';
import { Zap, Video, Instagram, Youtube } from 'lucide-react';
import { loadNicheHistory, profileForNiche } from '../lib/nicheHistory';

const PLATFORMS = [
    { id: 'tiktok', label: 'tiktok', icon: <Video size={13} /> },
    { id: 'instagram', label: 'instagram', icon: <Instagram size={13} /> },
    { id: 'youtube', label: 'youtube', icon: <Youtube size={13} /> },
];

const chip = (active) => `readout px-2.5 py-1.5 rounded-full border inline-flex items-center gap-1.5 transition-colors ${active
    ? 'bg-brass/20 text-brass border-brass/50'
    : 'bg-paper3 text-ink2 border-transparent hover:border-rule2'}`;

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

    return (
        <div className={`mt-4 rounded-input border transition-colors ${value.enabled ? 'border-brass/50 bg-brass/5' : 'border-rule'}`}>
            <label className={`flex items-start gap-2.5 p-3 select-none ${available ? 'cursor-pointer' : 'cursor-not-allowed opacity-60'}`}>
                <input
                    type="checkbox"
                    checked={value.enabled && available}
                    disabled={!available}
                    onChange={(e) => set({ enabled: e.target.checked })}
                    className="mt-0.5 w-4 h-4 shrink-0 accent-[var(--color-accent)] cursor-pointer"
                />
                <span className="min-w-0">
                    <span className="text-sm text-ink flex items-center gap-1.5 lowercase">
                        <Zap size={14} className="text-brass" /> publish the 3 best clips automatically
                    </span>
                    <span className="block text-xs text-muted mt-0.5 leading-relaxed">
                        {available
                            ? 'Highest viral scores, scheduled on Upload-Post in the next free 8h · 12h · 20h slots of the account — after what is already planned, never two posts at the same time.'
                            : 'Set your Upload-Post key in Settings to use this.'}
                    </span>
                </span>
            </label>

            {value.enabled && available && (
                <div className="px-3 pb-3 space-y-3 animate-fade">
                    {profileNames.length > 1 && (
                        <div>
                            <p className="eyebrow mb-1.5">account</p>
                            <div className="flex flex-wrap gap-1.5">
                                {profileNames.map((name) => (
                                    <button key={name} type="button" onClick={() => set({ profile: name })} className={chip(name === activeProfile)}>
                                        {name}
                                    </button>
                                ))}
                            </div>
                        </div>
                    )}
                    <div>
                        <p className="eyebrow mb-1.5">niche · hashtags</p>
                        <input
                            type="text"
                            value={value.niche}
                            onChange={(e) => set({ niche: e.target.value })}
                            placeholder="empty = the AI's guess for this video"
                            className="input-field text-sm"
                        />
                        {history.length > 0 && (
                            <div className="flex flex-wrap gap-1.5 mt-2">
                                {history.map((n) => (
                                    <button
                                        key={n}
                                        type="button"
                                        onClick={() => {
                                            const same = value.niche.toLowerCase() === n.toLowerCase();
                                            const known = profileForNiche(n);
                                            set({ niche: same ? '' : n, ...(!same && known && profileNames.includes(known) ? { profile: known } : {}) });
                                        }}
                                        className={chip(value.niche.toLowerCase() === n.toLowerCase())}
                                    >
                                        {n}
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>
                    <div>
                        <p className="eyebrow mb-1.5">platforms</p>
                        <div className="flex flex-wrap gap-1.5">
                            {PLATFORMS.map((p) => (
                                <button key={p.id} type="button" onClick={() => togglePlatform(p.id)} className={chip(value.platforms.includes(p.id))}>
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
