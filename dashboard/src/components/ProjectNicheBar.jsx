import { useEffect, useState } from 'react';
import { Video, Instagram, Youtube, Check } from 'lucide-react';
import NichePicker from './NichePicker';
import { profileForNiche } from '../lib/nicheHistory';

const PLATFORM_ICONS = {
    tiktok: <Video size={12} />,
    instagram: <Instagram size={12} />,
    youtube: <Youtube size={12} />,
};

const PLATFORM_NAMES = { tiktok: 'TikTok', instagram: 'Instagram', youtube: 'YouTube' };

function ProfileIcons({ connected = [] }) {
    const on = Object.keys(PLATFORM_ICONS).filter((p) => connected.includes(p));
    return (
        <span className="inline-flex items-center gap-1">
            {Object.entries(PLATFORM_ICONS).map(([p, icon]) => (
                <span key={p} aria-hidden="true" className={connected.includes(p) ? 'text-ink2' : 'text-muted opacity-40'}>{icon}</span>
            ))}
            {/* The dimmed icons say "not connected"; say it in words too. */}
            <span className="sr-only">
                {on.length ? `Connected: ${on.map((p) => PLATFORM_NAMES[p]).join(', ')}` : 'No network connected'}
            </span>
        </span>
    );
}

/**
 * Step 1 of every scheduling screen: this project's niche AND the account
 * (Upload-Post profile) it posts to — one account per niche, every account
 * posting on the same 8h / 12h / 20h slots.
 *
 *  - choice: null (not decided) | { niche: string ('' = no hashtags), profile }
 *  - proposed: prefill niche (the project's AI guess, else the last one used)
 *  - profiles: [{ username, connected: ['tiktok', …] }] from Upload-Post
 *  - defaultProfile: the account selected in Settings
 *  - onChoose(choice): parent stores it (and saves it on the project)
 *
 * The account row only shows when there's more than one profile to pick.
 */
export default function ProjectNicheBar({
    choice, proposed = '', isAiGuess = false, onChoose, disabled = false,
    profiles = [], defaultProfile = '',
}) {
    const [value, setValue] = useState(proposed);
    const [profile, setProfile] = useState(defaultProfile);
    useEffect(() => { if (!choice) setValue(proposed); }, [proposed, choice]);
    // Typing / picking a niche you've used before brings its account with it.
    useEffect(() => {
        if (choice) return;
        const remembered = profileForNiche(value);
        if (remembered && profiles.some((p) => p.username === remembered)) setProfile(remembered);
        else if (!profile) setProfile(defaultProfile);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [value, choice, profiles, defaultProfile]);

    const byName = (name) => profiles.find((p) => p.username === name);
    const multi = profiles.length > 1;

    if (choice) {
        const acct = byName(choice.profile);
        return (
            <div className="tray flex items-center justify-between gap-3 pl-3.5 pr-2 py-2">
                <dl className="min-w-0 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                    <div className="flex items-center gap-2 min-w-0">
                        <dt className="readout">Niche</dt>
                        <dd className="min-w-0 truncate">
                            {choice.niche
                                ? <span className="text-ink font-medium">{choice.niche}</span>
                                : <span className="text-muted">No hashtags</span>}
                        </dd>
                    </div>
                    {multi && choice.profile && (
                        <div className="flex items-center gap-2 min-w-0">
                            <dt className="readout">Account</dt>
                            <dd className="min-w-0 flex items-center gap-2">
                                <span className="text-ink2 truncate">{choice.profile}</span>
                                <ProfileIcons connected={acct?.connected || []} />
                            </dd>
                        </div>
                    )}
                </dl>
                <button
                    type="button"
                    disabled={disabled}
                    onClick={() => { setValue(choice.niche || proposed); setProfile(choice.profile || defaultProfile); onChoose(null); }}
                    className="btn-quiet shrink-0 px-3 py-1.5 text-xs bg-paper2"
                >
                    Change
                </button>
            </div>
        );
    }

    const confirm = () => { if (value.trim()) onChoose({ niche: value.trim(), profile: profile || defaultProfile }); };
    const selected = byName(profile);
    const noAccounts = multi && selected && !(selected.connected || []).length;

    return (
        <div className="rounded-card border border-rule2 bg-paper2 p-4 space-y-3.5">
            <div>
                <p className="text-sm font-medium text-ink">What's this project's niche{multi ? ' and account' : ''}?</p>
                <p className="text-xs text-muted mt-1 leading-relaxed">
                    {isAiGuess && value === proposed ? 'Guessed by AI from this video — confirm or pick another. ' : ''}
                    Asked once per project, used for the hashtags{multi ? ' and the account' : ''} of every post.
                </p>
            </div>
            <NichePicker value={value} onChange={setValue} onEnter={confirm} />
            {multi && (
                <div role="group" aria-label="Post on account">
                    <p className="readout mb-1.5" aria-hidden="true">Post on account</p>
                    <div className="flex flex-wrap gap-1.5">
                        {profiles.map((p) => {
                            const on = p.username === profile;
                            return (
                                <button
                                    key={p.username}
                                    type="button"
                                    onClick={() => setProfile(p.username)}
                                    aria-pressed={on}
                                    className={`min-h-[36px] [@media(pointer:coarse)]:min-h-[44px] px-3 py-1.5 rounded-input border text-xs inline-flex items-center gap-2 transition-colors ${on
                                        ? 'bg-vermilionsoft text-ink border-vermilion'
                                        : 'bg-paper3 text-ink2 border-transparent hover:border-rule2 hover:text-ink'}`}
                                >
                                    {p.username}
                                    <ProfileIcons connected={p.connected || []} />
                                </button>
                            );
                        })}
                    </div>
                    {noAccounts && (
                        <p className="text-xs text-warn mt-2">No social account is connected on “{profile}” yet — connect them at upload-post.com.</p>
                    )}
                </div>
            )}
            <div className="flex flex-wrap gap-2 justify-end">
                <button type="button" onClick={() => onChoose({ niche: '', profile: profile || defaultProfile })} className="btn-ghost px-3.5 py-2 text-xs">
                    No hashtags
                </button>
                <button type="button" onClick={confirm} disabled={!value.trim()} className="btn-primary px-4 py-2 text-xs">
                    <Check size={14} aria-hidden="true" />
                    Use this {multi ? 'niche & account' : 'niche'}
                </button>
            </div>
        </div>
    );
}
