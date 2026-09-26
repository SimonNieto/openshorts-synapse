import { useEffect, useState } from 'react';
import { Video, Instagram, Youtube } from 'lucide-react';
import NichePicker from './NichePicker';
import { profileForNiche } from '../lib/nicheHistory';

const PLATFORM_ICONS = {
    tiktok: <Video size={12} />,
    instagram: <Instagram size={12} />,
    youtube: <Youtube size={12} />,
};

function ProfileIcons({ connected = [] }) {
    return (
        <span className="inline-flex items-center gap-1">
            {Object.entries(PLATFORM_ICONS).map(([p, icon]) => (
                <span key={p} className={connected.includes(p) ? 'text-ink2' : 'text-muted/40'}>{icon}</span>
            ))}
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
            <div className="flex items-center justify-between gap-3 px-3 py-2.5 rounded-input bg-paper3 border border-rule">
                <span className="text-sm text-ink2 min-w-0 truncate flex items-center gap-2 flex-wrap">
                    <span className="eyebrow">niche</span>
                    {choice.niche
                        ? <span className="text-brass">{choice.niche}</span>
                        : <span className="text-muted">no hashtags</span>}
                    {multi && choice.profile && (
                        <>
                            <span className="eyebrow ml-2">account</span>
                            <span className="text-ink2">{choice.profile}</span>
                            <ProfileIcons connected={acct?.connected || []} />
                        </>
                    )}
                </span>
                <button
                    type="button"
                    disabled={disabled}
                    onClick={() => { setValue(choice.niche || proposed); setProfile(choice.profile || defaultProfile); onChoose(null); }}
                    className="readout px-2 py-1 rounded-full bg-paper2 hover:text-ink shrink-0"
                >
                    change
                </button>
            </div>
        );
    }

    const confirm = () => { if (value.trim()) onChoose({ niche: value.trim(), profile: profile || defaultProfile }); };
    const selected = byName(profile);
    const noAccounts = multi && selected && !(selected.connected || []).length;

    return (
        <div className="p-3 rounded-input border border-brass/50 bg-brass/5 space-y-3">
            <div>
                <p className="text-sm text-ink">What's this project's niche{multi ? ' and account' : ''}?</p>
                <p className="text-xs text-muted mt-0.5">
                    {isAiGuess && value === proposed ? 'Guessed by AI from this video — confirm or pick another. ' : ''}
                    Asked once per project, used for the hashtags{multi ? ' and the account' : ''} of every post.
                </p>
            </div>
            <NichePicker value={value} onChange={setValue} onEnter={confirm} />
            {multi && (
                <div>
                    <p className="eyebrow mb-1.5">post on account</p>
                    <div className="flex flex-wrap gap-1.5">
                        {profiles.map((p) => {
                            const on = p.username === profile;
                            return (
                                <button
                                    key={p.username}
                                    type="button"
                                    onClick={() => setProfile(p.username)}
                                    className={`readout px-2.5 py-1.5 rounded-full inline-flex items-center gap-2 border transition-colors ${on
                                        ? 'bg-brass/20 text-brass border-brass/50'
                                        : 'bg-paper3 hover:bg-paper2 text-ink2 border-transparent'}`}
                                >
                                    {p.username}
                                    <ProfileIcons connected={p.connected || []} />
                                </button>
                            );
                        })}
                    </div>
                    {noAccounts && (
                        <p className="text-xs text-warn mt-1.5">No social account is connected on “{profile}” yet — connect them at upload-post.com.</p>
                    )}
                </div>
            )}
            <div className="flex gap-2 justify-end">
                <button type="button" onClick={() => onChoose({ niche: '', profile: profile || defaultProfile })} className="btn-ghost px-3 py-1.5 text-xs">
                    no hashtags
                </button>
                <button type="button" onClick={confirm} disabled={!value.trim()} className="btn-primary px-4 py-1.5 text-xs">
                    ✓ use this {multi ? 'niche & account' : 'niche'}
                </button>
            </div>
        </div>
    );
}
