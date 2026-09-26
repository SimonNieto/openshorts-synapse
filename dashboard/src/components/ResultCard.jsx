import React, { useState, useEffect } from 'react';
import { Download, Share2, Instagram, Youtube, Video, AlertCircle, Loader2, Copy, Check, Wand2, Type, Languages, FileText, Link2, Scissors, Crosshair, TrendingUp, RefreshCw, Film } from 'lucide-react';
import { getApiUrl } from '../config';
import { apiFetch, apiJson } from '../lib/api';
import SubtitleModal from './SubtitleModal';
import HookModal from './HookModal';
import TranslateModal from './TranslateModal';
import Modal from './ui/Modal';
import NichePromptModal from './NichePromptModal';
import { pushNicheHistory } from '../lib/nicheHistory';
import { localDateStr, userTimezone } from '../lib/postSlots';
import NichePicker from './NichePicker';
import SegmentedControl from './ui/SegmentedControl';
import WatermarkModal, { watermarkNoticeDismissed } from './WatermarkModal';
import TikTokDraftNotice from './TikTokDraftNotice';
import { useAuth } from '../contexts/AuthContext';
import { renderInBrowser } from '../lib/renderInBrowser';

const QUIET_BTN = 'group flex flex-col items-center justify-center gap-1 py-2.5 sm:py-2 px-1 rounded-input border border-rule hover:bg-paper3 text-[11px] lowercase text-ink2 whitespace-nowrap transition-colors disabled:opacity-45 disabled:cursor-not-allowed';

const PLATFORM_OPTIONS = [
    { value: 'tiktok', label: 'tiktok', icon: <Video size={16} /> },
    { value: 'instagram', label: 'instagram', icon: <Instagram size={16} /> },
    { value: 'youtube', label: 'youtube', icon: <Youtube size={16} /> },
];

function clipDurationSeconds(clip) {
    // A recut clip's start/end are the covering source range (segments may be
    // non-contiguous or reordered); its real duration is the segment sum.
    const segments = clip.recipe?.segments;
    if (segments?.length) {
        return segments.reduce((acc, s) => acc + (s.end - s.start), 0);
    }
    return clip.end && clip.start ? clip.end - clip.start : NaN;
}

function formatDuration(clip) {
    const secs = Math.floor(clipDurationSeconds(clip));
    if (!Number.isFinite(secs) || secs < 0) return null;
    return `${String(Math.floor(secs / 60)).padStart(2, '0')}:${String(secs % 60).padStart(2, '0')}`;
}

const WHEN_OPTIONS = [
    { value: 'now', label: 'now' },
    { value: 'tonight', label: 'tonight 19:00' },
    { value: 'tomorrow', label: 'tomorrow 12:00' },
    { value: 'custom', label: 'pick…' },
];

// The one-click "when" chips as a local "YYYY-MM-DDTHH:MM:00" string (or null
// for "now"). "tonight" rolls to tomorrow once 19:00 is too close to make.
function resolveWhen(choice, customValue) {
    const at = (dayOffset, hh) => {
        const d = new Date();
        d.setDate(d.getDate() + dayOffset);
        return `${localDateStr(d)}T${hh}:00`;
    };
    if (choice === 'tonight') {
        const cutoff = new Date();
        cutoff.setHours(18, 45, 0, 0);
        return new Date() < cutoff ? at(0, '19:00') : at(1, '19:00');
    }
    if (choice === 'tomorrow') return at(1, '12:00');
    if (choice === 'custom') return customValue ? `${customValue}:00` : null;
    return null;
}

export default function ResultCard({ clip, index, jobId, durable, uploadPostKey, uploadUserId, geminiApiKey, elevenLabsKey, niche, isManaged, onPlay, onPause, onBulkSubtitle, clipCount = 1, bulkProgress, initialState = null, onStateChange, connectedPlatforms = null, onConnectSocials, onEditClip = null, onReframeClip = null, onPublished = null, onNicheUsed = null, plusProfileId = null }) {
    const [showModal, setShowModal] = useState(false);
    const [showDescModal, setShowDescModal] = useState(false);
    // Regenerated hook/title/descriptions override the original clip copy
    // until the page reloads (the backend persists the same fields into
    // metadata.json, so a reload picks them up as the new "clip" anyway).
    const [copyOverride, setCopyOverride] = useState(null);
    const [regeneratingCopy, setRegeneratingCopy] = useState(false);
    const [regenerateCopyError, setRegenerateCopyError] = useState('');
    const displayClip = copyOverride ? { ...clip, ...copyOverride } : clip;
    const [showSubtitleModal, setShowSubtitleModal] = useState(false);
    const [showWatermarkModal, setShowWatermarkModal] = useState(false);
    const { plan } = useAuth();
    const videoRef = React.useRef(null);
    // Pristine base clip (no burned subtitles/hook), stable regardless of how
    // clip.video_url mutates after server edits. Used as the compositing base
    // for the Remotion preview so it never stacks subtitles over an already-
    // subtitled file (double-subtitle bug).
    const stripBurns = (filename) => {
        let f = filename || '', prev;
        do { prev = f; f = f.replace(/^subtitled_\d+_/, '').replace(/^hooked_\d+_/, '').replace(/^hook_/, ''); } while (f !== prev);
        return f;
    };
    const originalVideoUrl = getApiUrl((clip.video_url || '').replace(/[^/]+$/, stripBurns((clip.video_url || '').split('/').pop())));
    const [currentVideoUrl, setCurrentVideoUrl] = useState(getApiUrl(clip.video_url));
    // Where the <video> element pulls its bytes from. The clips are archived to
    // R2 anyway, and R2 egress is free and edge-served, while /videos is served
    // by the same single-worker API process that is running the renders. So play
    // from R2 when possible.
    //
    // ONLY when R2 holds exactly the file the server considers current for this
    // clip (durable.filename === serverVideoFile). Every server-side edit sends
    // input_filename: serverVideoFile and rewrites clip.video_url, but the R2
    // re-archive behind it is fire-and-forget, so for a few seconds the durable
    // copy is the PRE-edit clip. Preferring it blindly would silently show the
    // clip without the subtitles/hook the user just burned.
    //
    // This is display-only: currentVideoUrl remains the source of truth for the
    // download button and for every server operation, so no edit can be routed
    // to the wrong file by this.
    const [durableSrc, setDurableSrc] = useState(null);
    const [durableFailed, setDurableFailed] = useState(false);
    // Switching src reloads the element and restarts playback, so the durable copy
    // is only ever adopted before the user has touched this player. After an edit
    // the chase in App.jsx can land while they are watching the result, and losing
    // their position to save a few seconds of buffering is a bad trade.
    const [hasPlayed, setHasPlayed] = useState(false);

    // A delivered clip is tens of MB, and on a slow link the old silent
    // fetch-then-save took minutes with nothing on screen, which reads as a dead
    // button. Stream it instead and report progress.
    const [downloadPct, setDownloadPct] = useState(null);

    // Shared with handleRegenerateCopy below: asked before EVERY action that
    // needs a niche (never silently reused — see NichePromptModal), resolved
    // via a modal instead of window.prompt so picking a recent one is a
    // click. Renders near the other modals further down this component.
    const [nichePrompt, setNichePrompt] = useState(null);
    const askNiche = (message, { skippable = true } = {}) => new Promise((resolve) => {
        setNichePrompt({
            message,
            defaultValue: niche || localStorage.getItem('openshorts_niche') || '',
            onSkip: skippable ? () => { setNichePrompt(null); resolve(''); } : undefined,
            onConfirm: (n) => {
                setNichePrompt(null);
                if (n) {
                    localStorage.setItem('openshorts_niche', n);
                    pushNicheHistory(n);
                    onNicheUsed?.(n); // becomes this project's niche
                }
                resolve(n);
            },
        });
    });

    // Plain text ready to paste into a posting form, downloaded alongside the
    // video. The texts come from the server's own caption builder
    // (/api/social/preview → app.py _captions_from_pool) — the same code an
    // Upload-Post send and the ZIP's .txt use — so the file can't differ from
    // what would be published: niche-generator hashtags only, title padded to
    // YouTube's 100 chars.
    const downloadCopyText = async () => {
        const activeNiche = await askNiche(
            "What's your channel's niche? (e.g. \"Joe Rogan podcast clips\") " +
            "Real hashtags for it will be added to this file. Leave blank to skip.");
        let hashtags = [];
        let captions = null;
        try {
            captions = await apiJson('/api/social/preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ job_id: jobId, clip_index: index, niche: activeNiche || null }),
            });
            if (activeNiche) {
                hashtags = (await apiJson(`/api/hashtags?niche=${encodeURIComponent(activeNiche)}`)).hashtags || [];
            }
        } catch { /* server unreachable — fall back to the raw AI copy below */ }

        const lines = [
            'YOUTUBE TITLE', captions?.youtube_title || displayClip.video_title_for_youtube_short || '(none)', '',
            'YOUTUBE DESCRIPTION', captions?.youtube_description || displayClip.video_description_for_instagram || '(none)', '',
            'TIKTOK DESCRIPTION', captions?.tiktok || displayClip.video_description_for_tiktok || '(none)', '',
            'INSTAGRAM DESCRIPTION', captions?.instagram || displayClip.video_description_for_instagram || '(none)',
        ];
        if (displayClip.viral_hook_text) lines.push('', 'ON-SCREEN HOOK', displayClip.viral_hook_text);
        if (hashtags.length) lines.push('', 'NICHE HASHTAGS', hashtags.join(' '));

        const blob = new Blob([lines.join('\n') + '\n'], { type: 'text/plain' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        a.download = `clip-${index + 1}-title-and-description.txt`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
    };

    const downloadClip = async () => {
        try {
            setDownloadPct(0);
            const response = await fetch(currentVideoUrl);
            if (!response.ok) throw new Error('Download failed');
            const total = Number(response.headers.get('content-length')) || 0;
            let blob;
            // No body reader (old browser) or no length to measure against: fall
            // back to the plain path rather than lose the download.
            if (!response.body || !total) {
                blob = await response.blob();
            } else {
                const reader = response.body.getReader();
                const chunks = [];
                let received = 0;
                for (;;) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    chunks.push(value);
                    received += value.length;
                    setDownloadPct(Math.min(99, Math.round((received / total) * 100)));
                }
                blob = new Blob(chunks, { type: 'video/mp4' });
            }
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = url;
            a.download = `clip-${index + 1}.mp4`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
            await downloadCopyText();
        } catch (err) {
            console.error('Download error:', err);
            window.open(currentVideoUrl, '_blank');
        } finally {
            setDownloadPct(null);
        }
    };
    // Latest file that exists ON THE SERVER (blob: previews don't count).
    // All server-side operations must chain from this, so burned-in edits
    // (subtitles, hooks, effects) never get silently dropped.
    // A reopened project seeds it from the persisted project state.
    const [serverVideoFile, setServerVideoFile] = useState(initialState?.server_file || (clip.video_url || '').split('/').pop());
    const [videoErrored, setVideoErrored] = useState(false);
    const [resolution, setResolution] = useState(null);

    // Adopt the durable copy only while it matches the current server file, and
    // pin the first signed URL seen for that file: /api/history mints a fresh
    // signature on every call, and swapping src mid-playback restarts the video.
    useEffect(() => {
        if (durable?.url && durable.filename && durable.filename === serverVideoFile && !hasPlayed) {
            setDurableSrc((prev) => prev || durable.url);
        } else {
            setDurableSrc(null);
        }
    }, [durable?.url, durable?.filename, serverVideoFile, hasPlayed]);

    // If the local video failed and a durable R2 URL is (now) available, use it.
    // Handles the race where the video errors before the durable URL has loaded.
    // Deliberately NOT version-gated: reaching here means the local file is gone
    // (retention sweep after a reload), so an older durable copy still beats a
    // broken player.
    useEffect(() => {
        if (videoErrored && durable?.url && currentVideoUrl !== durable.url) {
            setCurrentVideoUrl(durable.url);
            setVideoErrored(false);
        }
    }, [videoErrored, durable, currentVideoUrl]);

    // When an external refresh changes this clip's server file (e.g. bulk
    // subtitles applied from another card), adopt it so the card shows the
    // freshly subtitled video instead of a stale one.
    useEffect(() => {
        const serverUrl = getApiUrl(clip.video_url);
        const serverName = (clip.video_url || '').split('/').pop();
        if (serverName && serverName !== serverVideoFile) {
            setServerVideoFile(serverName);
            setCurrentVideoUrl(serverUrl);
            setDurableFailed(false);
            setHasPlayed(false);
            if (videoRef.current) videoRef.current.load();
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [clip.video_url]);

    const [platforms, setPlatforms] = useState({
        tiktok: true,
        instagram: true,
        youtube: true
    });
    const [postTitle, setPostTitle] = useState("");
    const [postDescription, setPostDescription] = useState("");
    // One-click "when": now / tonight / tomorrow, or a custom date-time.
    const [whenChoice, setWhenChoice] = useState('now');
    const isScheduling = whenChoice !== 'now';
    const [scheduleDate, setScheduleDate] = useState("");
    const [postNiche, setPostNiche] = useState("");
    // What the form was prefilled with: untouched fields are NOT sent, so the
    // server can give each platform its own caption (+ niche hashtags)
    // instead of forcing the Instagram text onto TikTok and YouTube.
    const [postPrefill, setPostPrefill] = useState({ title: '', description: '' });

    const [posting, setPosting] = useState(false);
    const [postResult, setPostResult] = useState(null);
    const [copied, setCopied] = useState(null);

    const handleCopy = async (field, text) => {
        try {
            await navigator.clipboard.writeText(text || '');
            setCopied(field);
            setTimeout(() => setCopied(null), 2000);
        } catch {
            // clipboard unavailable — silent
        }
    };

    const handleRegenerateCopy = async () => {
        if (regeneratingCopy) return;
        setRegeneratingCopy(true);
        setRegenerateCopyError('');
        try {
            const apiKey = geminiApiKey || localStorage.getItem('gemini_key');
            if (!apiKey && !isManaged) {
                throw new Error('Gemini API Key is missing. Please set it in Settings.');
            }
            // Real, researched hashtags need to know the channel's niche —
            // asked every time rather than silently reusing whatever was
            // used last (this clip might not be in the same niche).
            const activeNiche = await askNiche(
                "What's your channel's niche? (e.g. \"Joe Rogan podcast clips\") " +
                "Used to research real, on-topic hashtags. Leave blank to skip.");
            setCopyOverride(await apiJson(`/api/clip/${jobId}/${index}/regenerate-copy`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...(apiKey ? { 'X-Gemini-Key': apiKey } : {}) },
                body: JSON.stringify({ niche: activeNiche || null }),
            }));
        } catch (e) {
            setRegenerateCopyError(e.detail || e.message || 'Failed to generate new copy');
        } finally {
            setRegeneratingCopy(false);
        }
    };

    const [isEditing, setIsEditing] = useState(false);
    // Viral edit styles (viral_fx.py): jump zooms + colour key-word captions.
    const [stylePicker, setStylePicker] = useState(false);
    const [isSubtitling, setIsSubtitling] = useState(false);
    const [isHooking, setIsHooking] = useState(false);
    const [isTranslating, setIsTranslating] = useState(false);
    const [showHookModal, setShowHookModal] = useState(false);
    const [showTranslateModal, setShowTranslateModal] = useState(false);
    const [editError, setEditError] = useState(null);

    const [clipDuration, setClipDuration] = useState(() => {
        const secs = clipDurationSeconds(clip);
        return Number.isFinite(secs) ? secs : 30;
    });

    // Accumulate Remotion layers across operations. A reopened project restores
    // the layers persisted in its project state, so the next edit composes over
    // them instead of silently dropping previous browser-side work.
    const [activeLayers, setActiveLayers] = useState(initialState?.active_layers || { subtitles: null, hook: null, effects: null });

    // Report edit state upward (debounced sync to the project record). Skip the
    // mount run: only user-driven changes are worth persisting.
    const stateReported = React.useRef(false);
    useEffect(() => {
        if (!stateReported.current) { stateReported.current = true; return; }
        onStateChange?.(index, { activeLayers, serverVideoFile });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [activeLayers, serverVideoFile]);

    // True when the current server file already carries burned-in content.
    // Browser (Remotion) renders compose over the ORIGINAL clip, so using them
    // here would silently drop those burns — chain via server FFmpeg instead.
    const hasServerBurns = /(^|_)(subtitled|hook|hooked)_/.test(serverVideoFile || '');

    // The hook currently burned into the server file (auto-hook or a manual
    // one). /api/hook REPLACES it; tracked locally so the modal stays honest
    // after edits without refetching the job.
    const [burnedHook, setBurnedHook] = useState(clip.auto_hook?.text || null);

    // Fetch clip duration from transcript endpoint
    useEffect(() => {
        if (!jobId || index === undefined) return;
        apiFetch(`/api/clip/${jobId}/${index}/transcript`)
            .then(res => res.ok ? res.json() : null)
            .then(data => {
                if (data && data.durationSec) setClipDuration(data.durationSec);
            })
            .catch(() => {});
    }, [jobId, index]);

    // Which platforms the selected profile actually has linked. `null` means
    // unknown (profile list not loaded) — in that case nothing is gated.
    const knownConnections = Array.isArray(connectedPlatforms);
    const noAccountsConnected = knownConnections && connectedPlatforms.length === 0;
    const platformOptions = knownConnections
        ? PLATFORM_OPTIONS.map((o) => (connectedPlatforms.includes(o.value) ? o : { ...o, disabled: true, hint: 'not connected' }))
        : PLATFORM_OPTIONS;

    const handleConnectAccounts = () => {
        setShowModal(false);
        if (onConnectSocials) onConnectSocials();
        else window.open('https://app.upload-post.com', '_blank', 'noopener');
    };

    // Initialize/Reset form when modal opens
    useEffect(() => {
        if (showModal) {
            const title = displayClip.video_title_for_youtube_short || "Viral Short";
            const description = displayClip.video_description_for_instagram || displayClip.video_description_for_tiktok || "";
            setPostTitle(title);
            setPostDescription(description);
            setPostPrefill({ title, description });
            setPostNiche(niche || localStorage.getItem('openshorts_niche') || '');
            setWhenChoice('now');
            setScheduleDate("");
            setPostResult(null);
            // Only preselect platforms the profile can actually publish to.
            if (knownConnections) {
                setPlatforms({
                    tiktok: connectedPlatforms.includes('tiktok'),
                    instagram: connectedPlatforms.includes('instagram'),
                    youtube: connectedPlatforms.includes('youtube'),
                });
            }
        }
        // Reset only when the modal opens for a clip; connection changes while
        // it is open must not wipe the user's selection.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [showModal, clip]);

    // Rebuilt server-side from the clean clip every time, so switching style
    // (or applying twice) never stacks zooms.
    const handleViralStyle = async (style) => {
        setStylePicker(false);
        setIsEditing(true);
        try {
            const data = await apiJson(`/api/clip/${jobId}/${index}/viral-edit`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ style, profile_id: plusProfileId || null }),
            });
            if (data.new_video_url) {
                setCurrentVideoUrl(getApiUrl(data.new_video_url));
                setServerVideoFile(data.new_video_url.split('/').pop());
                if (videoRef.current) videoRef.current.load();
            }
        } catch (e) {
            setEditError(e.detail || e.message);
            setTimeout(() => setEditError(null), 6000);
        } finally {
            setIsEditing(false);
        }
    };

    const handleAutoEdit = async () => {
        setIsEditing(true);
        setEditError(null);
        try {
            const apiKey = geminiApiKey || localStorage.getItem('gemini_key');

            // Managed (paid) users get the Gemini key resolved server-side;
            // only BYOK/self-host needs a local key.
            if (!apiKey && !isManaged) {
                throw new Error("Gemini API Key is missing. Please set it in Settings.");
            }
            const geminiHeaders = apiKey ? { 'X-Gemini-Key': apiKey } : {};

            // Try Remotion effects endpoint first
            const effectsRes = hasServerBurns ? null : await apiFetch('/api/effects/generate', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...geminiHeaders
                },
                body: JSON.stringify({
                    job_id: jobId,
                    clip_index: index,
                    input_filename: serverVideoFile
                })
            });

            if (effectsRes && effectsRes.ok) {
                const data = await effectsRes.json();
                if (data.effects && data.effects.segments) {
                    const newLayers = { ...activeLayers, effects: data.effects };
                    setActiveLayers(newLayers);
                    const blobUrl = await renderInBrowser({
                        videoUrl: originalVideoUrl,
                        durationInSeconds: clipDuration,
                        subtitles: newLayers.subtitles,
                        hook: newLayers.hook,
                        effects: newLayers.effects,
                    });
                    setCurrentVideoUrl(blobUrl);
                    if (videoRef.current) videoRef.current.load();
                    return;
                }
            }

            // Fallback: legacy FFmpeg edit endpoint
            const res = await apiFetch('/api/edit', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...geminiHeaders
                },
                body: JSON.stringify({
                    job_id: jobId,
                    clip_index: index,
                    input_filename: serverVideoFile
                })
            });

            if (!res.ok) {
                const errText = await res.text();
                try {
                    const jsonErr = JSON.parse(errText);
                    throw new Error(jsonErr.detail || errText);
                } catch (e) {
                    throw new Error(errText);
                }
            }

            const data = await res.json();
            if (data.new_video_url) {
                setCurrentVideoUrl(getApiUrl(data.new_video_url));
                setServerVideoFile(data.new_video_url.split('/').pop());
                if (videoRef.current) {
                    videoRef.current.load();
                }
            }

        } catch (e) {
            setEditError(e.message);
            setTimeout(() => setEditError(null), 5000);
        } finally {
            setIsEditing(false);
        }
    };

    // Clips are captioned by default, so "no captions" has to be reachable.
    // Nothing is re-encoded: the server still holds the clean file next to the
    // captioned one and just points this clip back at it.
    const handleRemoveSubtitles = async () => {
        setIsSubtitling(true);
        setEditError(null);
        try {
            const res = await apiFetch('/api/subtitle/remove', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_id: jobId, clip_index: index, input_filename: serverVideoFile,
                }),
            });
            if (!res.ok) throw new Error(await res.text());
            const data = await res.json();
            if (data.new_video_url) {
                const serverUrl = getApiUrl(data.new_video_url);
                setServerVideoFile(data.new_video_url.split('/').pop());
                const remaining = { ...activeLayers, subtitles: null };
                setActiveLayers(remaining);
                if (remaining.hook || remaining.effects) {
                    setCurrentVideoUrl(await renderInBrowser({
                        videoUrl: serverUrl,
                        durationInSeconds: clipDuration,
                        subtitles: null,
                        hook: remaining.hook,
                        effects: remaining.effects,
                    }));
                } else {
                    setCurrentVideoUrl(serverUrl);
                }
                if (videoRef.current) videoRef.current.load();
                setShowSubtitleModal(false);
            }
        } catch (e) {
            setEditError(e.message);
            setTimeout(() => setEditError(null), 5000);
        } finally {
            setIsSubtitling(false);
        }
    };

    const handleSubtitle = async (options) => {
        setIsSubtitling(true);
        setEditError(null);
        try {
            // Karaoke styles are burned server-side (ASS word-highlight render);
            // the in-browser Remotion path only handles classic styles, and only
            // when the server file has no burned-in content to preserve.
            if (options.remotion && options.style !== 'karaoke' && !hasServerBurns) {
                // Accumulate layer and render all layers together
                const newLayers = { ...activeLayers, subtitles: options.remotion };
                setActiveLayers(newLayers);
                const blobUrl = await renderInBrowser({
                    videoUrl: originalVideoUrl,
                    durationInSeconds: clipDuration,
                    subtitles: newLayers.subtitles,
                    hook: newLayers.hook,
                    effects: newLayers.effects,
                });
                setCurrentVideoUrl(blobUrl);
                if (videoRef.current) videoRef.current.load();
                setShowSubtitleModal(false);
                return;
            }

            // Fallback: legacy FFmpeg
            const res = await apiFetch('/api/subtitle', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_id: jobId,
                    clip_index: index,
                    position: options.position,
                    position_percent: options.positionPercent ?? (typeof options.position === 'number' ? options.position : null),
                    font_size: options.fontSize,
                    font_name: options.fontName,
                    font_color: options.fontColor,
                    border_color: options.borderColor,
                    border_width: options.borderWidth,
                    bg_color: options.bgColor,
                    bg_opacity: options.bgOpacity,
                    style: options.style || 'classic',
                    highlight_color: options.highlightColor || '#FFD700',
                    effect: options.effect || 'none',
                    base_opacity: options.baseOpacity ?? 1.0,
                    uppercase: options.uppercase || false,
                    max_chars: options.maxChars ?? 16,
                    max_duration: options.maxDuration ?? 1.4,
                    letter_spacing: options.letterSpacing ?? 0,
                    max_words: options.maxWords ?? null,
                    input_filename: serverVideoFile,
                    // Edited caption text (clip-relative ms); null = server
                    // regenerates from the transcript as before.
                    words: options.captions || null
                })
            });

            if (!res.ok) throw new Error(await res.text());
            const data = await res.json();
            if (data.new_video_url) {
                const serverUrl = getApiUrl(data.new_video_url);
                setServerVideoFile(data.new_video_url.split('/').pop());
                // Subtitles are burned into the server file now — drop the
                // browser subtitle layer and re-compose any remaining browser
                // layers (hook/effects) over the new file so they aren't lost.
                const remaining = { ...activeLayers, subtitles: null };
                setActiveLayers(remaining);
                if (remaining.hook || remaining.effects) {
                    const blobUrl = await renderInBrowser({
                        videoUrl: serverUrl,
                        durationInSeconds: clipDuration,
                        subtitles: null,
                        hook: remaining.hook,
                        effects: remaining.effects,
                    });
                    setCurrentVideoUrl(blobUrl);
                } else {
                    setCurrentVideoUrl(serverUrl);
                }
                if (videoRef.current) videoRef.current.load();
                setShowSubtitleModal(false);
            }
        } catch (e) {
            setEditError(e.message);
            setTimeout(() => setEditError(null), 5000);
        } finally {
            setIsSubtitling(false);
        }
    };

    const handleHook = async (hookData) => {
        setIsHooking(true);
        setEditError(null);
        try {
            if (hookData.remotion && !hasServerBurns) {
                // Accumulate layer and render all layers together
                const newLayers = { ...activeLayers, hook: hookData.remotion };
                setActiveLayers(newLayers);
                const blobUrl = await renderInBrowser({
                    videoUrl: originalVideoUrl,
                    durationInSeconds: clipDuration,
                    subtitles: newLayers.subtitles,
                    hook: newLayers.hook,
                    effects: newLayers.effects,
                });
                setCurrentVideoUrl(blobUrl);
                if (videoRef.current) videoRef.current.load();
                setShowHookModal(false);
                return;
            }

            // Fallback: legacy FFmpeg
            const payload = typeof hookData === 'string'
                ? { text: hookData, position: 'top', size: 'M' }
                : hookData;

            const res = await apiFetch('/api/hook', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_id: jobId,
                    clip_index: index,
                    text: payload.text,
                    position: payload.position,
                    size: payload.size,
                    style: payload.style || 'classic',
                    duration_seconds: payload.remotion?.displayDurationSec ?? null,
                    input_filename: serverVideoFile
                })
            });

            if (!res.ok) throw new Error(await res.text());
            const data = await res.json();
            if (data.new_video_url) {
                setCurrentVideoUrl(getApiUrl(data.new_video_url));
                setServerVideoFile(data.new_video_url.split('/').pop());
                setBurnedHook(data.burned_hook?.text ?? payload.text ?? null);
                if (videoRef.current) videoRef.current.load();
                setShowHookModal(false);
            }
        } catch (e) {
            setEditError(e.message);
            setTimeout(() => setEditError(null), 5000);
        } finally {
            setIsHooking(false);
        }
    };

    // Strip the burned hook (auto-hook or manual) off the server file.
    const handleRemoveHook = async () => {
        setIsHooking(true);
        setEditError(null);
        try {
            const res = await apiFetch('/api/hook', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_id: jobId,
                    clip_index: index,
                    remove: true,
                    input_filename: serverVideoFile,
                }),
            });
            if (!res.ok) throw new Error(await res.text());
            const data = await res.json();
            if (data.new_video_url) {
                setCurrentVideoUrl(getApiUrl(data.new_video_url));
                setServerVideoFile(data.new_video_url.split('/').pop());
                setBurnedHook(null);
                if (videoRef.current) videoRef.current.load();
                setShowHookModal(false);
            }
        } catch (e) {
            setEditError(e.message);
            setTimeout(() => setEditError(null), 5000);
        } finally {
            setIsHooking(false);
        }
    };

    const handleTranslate = async (options) => {
        console.log('[Translate] Starting translation with options:', options);
        setIsTranslating(true);
        setEditError(null);
        try {
            const apiKey = elevenLabsKey;
            console.log('[Translate] API Key available:', !!apiKey);

            if (!apiKey) {
                throw new Error("ElevenLabs API Key is missing. Please set it in Settings.");
            }

            const requestBody = {
                job_id: jobId,
                clip_index: index,
                target_language: options.targetLanguage,
                input_filename: serverVideoFile
            };
            console.log('[Translate] Request body:', requestBody);
            console.log('[Translate] Sending request to /api/translate');

            const res = await apiFetch('/api/translate', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-ElevenLabs-Key': apiKey
                },
                body: JSON.stringify(requestBody)
            });

            console.log('[Translate] Response status:', res.status);

            if (!res.ok) {
                const errText = await res.text();
                console.error('[Translate] Error response:', errText);
                try {
                    const jsonErr = JSON.parse(errText);
                    throw new Error(jsonErr.detail || errText);
                } catch (e) {
                    if (e.message !== errText) throw e;
                    throw new Error(errText);
                }
            }

            const data = await res.json();
            console.log('[Translate] Success response:', data);
            if (data.new_video_url) {
                setCurrentVideoUrl(getApiUrl(data.new_video_url));
                setServerVideoFile(data.new_video_url.split('/').pop());
                if (videoRef.current) {
                    videoRef.current.load();
                }
                setShowTranslateModal(false);
            }

        } catch (e) {
            console.error('[Translate] Exception:', e);
            setEditError(e.message);
            setTimeout(() => setEditError(null), 5000);
        } finally {
            setIsTranslating(false);
        }
    };

    // Managed (cloud plan/trial) users post with the server-side key — no BYOK needed
    const canPost = isManaged || (uploadPostKey && uploadUserId);

    const handlePost = async () => {
        if (!canPost) {
            setPostResult({ success: false, msg: "Missing API Key or User ID." });
            return;
        }

        if (noAccountsConnected) {
            setPostResult({ success: false, msg: "Connect a social account first." });
            return;
        }

        const selectedPlatforms = Object.keys(platforms).filter(k => platforms[k]);
        if (selectedPlatforms.length === 0) {
            setPostResult({ success: false, msg: "Select at least one platform." });
            return;
        }

        const scheduledLocal = resolveWhen(whenChoice, scheduleDate);
        if (isScheduling && !scheduledLocal) {
            setPostResult({ success: false, msg: "Please select a date and time." });
            return;
        }

        setPosting(true);
        setPostResult(null);

        try {
            const trimmedNiche = postNiche.trim();
            if (trimmedNiche) {
                localStorage.setItem('openshorts_niche', trimmedNiche);
                pushNicheHistory(trimmedNiche);
                onNicheUsed?.(trimmedNiche); // becomes this project's niche
            }
            const payload = {
                job_id: jobId,
                clip_index: index,
                api_key: uploadPostKey,
                user_id: uploadUserId,
                platforms: selectedPlatforms,
                niche: trimmedNiche || null,
                // Always sent: also dates a "now" post in the Publish Plan.
                timezone: userTimezone(),
            };
            // Only send what the user actually edited — see postPrefill.
            if (postTitle !== postPrefill.title) payload.title = postTitle;
            if (postDescription !== postPrefill.description) payload.description = postDescription;

            if (scheduledLocal) {
                // Local wall-clock time + IANA zone (what Upload-Post expects,
                // and what the Publish Plan records), never a UTC ISO string.
                payload.scheduled_date = scheduledLocal;
            }

            const res = await apiFetch('/api/social/post', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (!res.ok) {
                const errText = await res.text();
                try {
                    const jsonErr = JSON.parse(errText);
                    throw new Error(jsonErr.detail || errText);
                } catch (e) {
                    throw new Error(errText);
                }
            }

            setPostResult({ success: true, msg: isScheduling ? "Scheduled — clip moved out of the project." : "Posted — clip moved out of the project." });
            setTimeout(() => {
                setShowModal(false);
                setPostResult(null);
                // The server took the clip out of the project; let the grid
                // drop this card so it can't be posted a second time.
                onPublished?.();
            }, 2000);

        } catch (e) {
            setPostResult({ success: false, msg: `Failed: ${e.message}` });
        } finally {
            setPosting(false);
        }
    };

    // Browser-rendered previews (Remotion) live in a blob: URL that exists only
    // in this tab, so they always win over the durable copy.
    const playbackUrl = (durableSrc && !durableFailed && !String(currentVideoUrl || '').startsWith('blob:'))
        ? durableSrc
        : currentVideoUrl;

    const durationReadout = formatDuration(clip);

    return (
        <div className="card overflow-hidden flex flex-col md:flex-row group hover:border-rule2 transition-colors animate-fade md:min-h-[420px]" style={{ animationDelay: `${index * 0.1}s` }}>
            {/* Left: Video Preview — 9:16 column matching the fixed card height */}
            {/* A full-width 9:16 preview on a phone is ~640px tall on its own,
                which pushed the title, captions and every action off-screen.
                Capping the height and centring keeps the whole card scannable
                without letterboxing the clip. */}
            <div className="w-full max-w-[calc(64vh*0.5625)] md:max-w-none mx-auto md:mx-0 md:w-[236px] bg-black relative shrink-0 aspect-[9/16] md:aspect-auto group/video">
                <video
                    ref={videoRef}
                    // #t=0.1 makes the browser paint the first real frame
                    // instead of a black box until the clip is played.
                    src={playbackUrl && !playbackUrl.includes('#') ? `${playbackUrl}#t=0.1` : playbackUrl}
                    preload="metadata"
                    controls
                    className="w-full h-full object-contain"
                    playsInline
                    onLoadedMetadata={(e) => {
                        if (e.target.videoWidth) setResolution(`${e.target.videoWidth}×${e.target.videoHeight}`);
                    }}
                    onError={() => {
                        // The durable copy is unreachable (signature expired after an
                        // hour on an idle tab, object purged) → serve from the API for
                        // the rest of this card's life.
                        if (playbackUrl === durableSrc) {
                            setDurableFailed(true);
                            return;
                        }
                        // Local /videos/ file gone (e.g. cleaned up after a reload) →
                        // fall back to the durable R2 copy for managed users. If the
                        // durable URL hasn't loaded yet, the effect above retries.
                        if (durable?.url && currentVideoUrl !== durable.url) setCurrentVideoUrl(durable.url);
                        else setVideoErrored(true);
                    }}
                    onPlay={() => {
                        setHasPlayed(true);
                        const currentTime = videoRef.current ? videoRef.current.currentTime : 0;
                        onPlay && onPlay(clip.start + currentTime);
                    }}
                    onPause={() => onPause && onPause()}
                    onEnded={() => {
                        if (videoRef.current) {
                            videoRef.current.currentTime = 0;
                            videoRef.current.play();
                        }
                    }}
                />
                <div className="absolute top-3 left-3 flex gap-2">
                    {/* Stays the clip's own number, not its rank: the cards are
                        ordered by score, but this is what the downloaded file
                        is called (clip-N.mp4) and what every api call indexes. */}
                    <span className="bg-black/70 text-ink font-mono text-micro uppercase px-2 py-1 rounded-full">
                        Clip {index + 1}
                    </span>
                    {/* A bare number on a thumbnail reads as a duration, a
                        position, anything — it has to name itself and carry
                        its scale, or it is decoration. */}
                    {Number.isFinite(clip.predicted_score) && (
                        <span
                            className="bg-black/70 font-mono text-micro uppercase px-2 py-1 rounded-full flex items-center gap-1"
                            title="openshorts' prediction of how well this clip will perform, from 0 to 100"
                        >
                            <TrendingUp size={11} className="shrink-0 text-muted" />
                            <span className="text-muted">viral</span>
                            <b className={
                                clip.predicted_score >= 80 ? 'text-ok'
                                    : clip.predicted_score >= 65 ? 'text-brass'
                                        : 'text-ink2'
                            }>
                                {clip.predicted_score}
                            </b>
                            <span className="text-muted">/100</span>
                        </span>
                    )}
                </div>

                {/* Auto Edit Overlay if Processing */}
                {isEditing && (
                    <div className="absolute inset-0 bg-black/70 flex flex-col items-center justify-center z-10 p-4 text-center">
                        <Loader2 size={28} className="text-brass animate-spin mb-3" />
                        <span className="text-xs text-ink lowercase">ai magic in progress…</span>
                        <span className="readout mt-1.5">APPLYING VIRAL EDITS · ZOOMS</span>
                    </div>
                )}
            </div>

            {/* Right: Content & Details */}
            <div className="flex-1 p-4 md:p-5 flex flex-col overflow-hidden min-w-0">
                <div className="mb-4">
                    <h3 className="text-base font-medium text-ink leading-tight line-clamp-2 mb-2 break-words" title={displayClip.video_title_for_youtube_short}>
                        {displayClip.video_title_for_youtube_short || "Viral Clip Generated"}
                    </h3>
                    <div className="flex flex-wrap gap-1.5">
                        {durationReadout && <span className="readout bg-paper3 px-2 py-0.5 rounded-full shrink-0">{durationReadout}</span>}
                        {resolution && <span className="readout bg-paper3 px-2 py-0.5 rounded-full shrink-0">{resolution}</span>}
                    </div>
                </div>

                {/* Descriptions (compact) — full text lives in the modal */}
                <div className="flex-1 min-h-0 space-y-2 mb-4">
                    <div className="bg-paper rounded-input px-3 py-2 border border-rule flex items-center gap-2 min-w-0">
                        <span className="eyebrow shrink-0">YOUTUBE</span>
                        <p className="text-xs text-ink2 truncate flex-1 min-w-0">
                            {displayClip.video_title_for_youtube_short || "Viral Short Video"}
                        </p>
                        <button
                            onClick={() => handleCopy('youtube', displayClip.video_title_for_youtube_short || "Viral Short Video")}
                            aria-label="copy youtube title"
                            className="p-1 rounded-full text-muted hover:text-brass transition-colors shrink-0"
                        >
                            {copied === 'youtube' ? <Check size={14} className="text-ok" /> : <Copy size={14} />}
                        </button>
                    </div>

                    <div className="bg-paper rounded-input px-3 py-2 border border-rule flex items-center gap-2 min-w-0">
                        <span className="eyebrow shrink-0">TIKTOK · IG</span>
                        <p className="text-xs text-ink2 truncate flex-1 min-w-0">
                            {displayClip.video_description_for_tiktok || displayClip.video_description_for_instagram}
                        </p>
                        <button
                            onClick={() => handleCopy('caption', displayClip.video_description_for_tiktok || displayClip.video_description_for_instagram)}
                            aria-label="copy caption"
                            className="p-1 rounded-full text-muted hover:text-brass transition-colors shrink-0"
                        >
                            {copied === 'caption' ? <Check size={14} className="text-ok" /> : <Copy size={14} />}
                        </button>
                    </div>

                    <button
                        onClick={() => setShowDescModal(true)}
                        className="w-full flex items-center justify-center gap-2 py-2 rounded-input border border-dashed border-rule text-xs lowercase text-muted hover:text-brass hover:border-rule2 transition-colors"
                    >
                        <FileText size={14} /> view descriptions
                    </button>
                </div>

                {/* Error Message */}
                {editError && (
                    <div className="mb-3 px-3 py-2 rounded-input text-xs text-danger bg-[color-mix(in_oklab,var(--color-danger)_10%,transparent)] flex items-center gap-2">
                        <AlertCircle size={14} className="shrink-0" />
                        {editError}
                    </div>
                )}

                {/* Actions Footer */}
                <div className="grid grid-cols-2 gap-2 mt-auto pt-4 border-t border-rule">
                    {onEditClip && (
                        <button
                            onClick={() => onEditClip(index)}
                            className={QUIET_BTN}
                        >
                            <Scissors size={16} className="text-muted group-hover:text-brass transition-colors shrink-0" />
                            edit clip
                        </button>
                    )}

                    {onReframeClip && (
                        <button
                            onClick={() => onReframeClip(index)}
                            className={QUIET_BTN}
                        >
                            <Crosshair size={16} className="text-muted group-hover:text-brass transition-colors shrink-0" />
                            reframing
                        </button>
                    )}

                    <button
                        onClick={handleAutoEdit}
                        disabled={isEditing}
                        className={QUIET_BTN}
                    >
                        {isEditing ? <Loader2 size={16} className="animate-spin text-brass shrink-0" /> : <Wand2 size={16} className="text-muted group-hover:text-brass transition-colors shrink-0" />}
                        {isEditing ? 'editing…' : 'auto edit'}
                    </button>

                    <button
                        onClick={() => setStylePicker((v) => !v)}
                        disabled={isEditing}
                        className={QUIET_BTN}
                        title="Jump zooms + big captions with coloured key words, like viral podcast shorts"
                    >
                        <Film size={16} className="text-muted group-hover:text-brass transition-colors shrink-0" />
                        viral style
                    </button>
                    {stylePicker && (
                        <div className="col-span-2 flex flex-wrap items-center gap-2 p-2 rounded-input border border-rule bg-paper">
                            <button type="button" onClick={() => handleViralStyle('natural')} className="btn-quiet px-3 py-1.5 text-xs" title="2-3 plain white words, calm reframes at sentence ends — like the big podcast channels">natural</button>
                            <button type="button" onClick={() => handleViralStyle('punchy')} className="btn-quiet px-3 py-1.5 text-xs" title="1-2 big glowing words, colour key words, zooms + shake, warm grade">punchy</button>
                            <button type="button" onClick={() => handleViralStyle('clean')} className="btn-quiet px-3 py-1.5 text-xs" title="2-4 words, one coloured key word, softer zooms, dips to black">clean</button>
                            <span className="text-[11px] text-muted">replaces this clip's captions</span>
                        </div>
                    )}

                    <button
                        onClick={() => setShowSubtitleModal(true)}
                        disabled={isSubtitling}
                        className={QUIET_BTN}
                    >
                        {isSubtitling ? <Loader2 size={16} className="animate-spin text-brass shrink-0" /> : <Type size={16} className="text-muted group-hover:text-brass transition-colors shrink-0" />}
                        {isSubtitling ? 'adding…' : 'subtitles'}
                    </button>

                    <button
                        onClick={() => setShowHookModal(true)}
                        disabled={isHooking}
                        className={QUIET_BTN}
                    >
                        {isHooking ? <Loader2 size={16} className="animate-spin text-brass shrink-0" /> : <Wand2 size={16} className="text-muted group-hover:text-brass transition-colors shrink-0" />}
                        {isHooking ? 'adding…' : 'viral hook'}
                    </button>

                    <button
                        onClick={() => setShowTranslateModal(true)}
                        disabled={isTranslating}
                        className={QUIET_BTN}
                    >
                        {isTranslating ? <Loader2 size={16} className="animate-spin text-brass shrink-0" /> : <Languages size={16} className="text-muted group-hover:text-brass transition-colors shrink-0" />}
                        {isTranslating ? 'translating…' : 'dub voice'}
                    </button>

                    <button
                        onClick={() => setShowModal(true)}
                        className="btn-primary flex-col gap-1 py-2.5 sm:py-2 px-1 text-[11px] leading-none rounded-input whitespace-nowrap"
                    >
                        <Share2 size={16} className="shrink-0" /> post
                    </button>
                    <button
                        onClick={(e) => {
                            e.preventDefault();
                            // Free clips are watermarked — surface the upsell once
                            // before the first download, then get out of the way.
                            if (plan === 'free' && !watermarkNoticeDismissed()) {
                                setShowWatermarkModal(true);
                                return;
                            }
                            downloadClip();
                        }}
                        className={`${QUIET_BTN}${onEditClip ? ' col-span-2' : ''}`}
                    >
                        <Download size={16} className="text-muted group-hover:text-brass transition-colors shrink-0" />
                        {downloadPct === null ? 'download' : `downloading ${downloadPct}%`}
                    </button>
                </div>
            </div>

            {/* Descriptions Modal */}
            <Modal
                isOpen={showDescModal}
                onClose={() => setShowDescModal(false)}
                eyebrow="GENERATED COPY"
                title="descriptions"
                size="md"
            >
                <div className="space-y-4">
                    <button
                        onClick={handleRegenerateCopy}
                        disabled={regeneratingCopy}
                        className="w-full flex items-center justify-center gap-2 py-2 rounded-input border border-dashed border-rule text-xs lowercase text-muted hover:text-brass hover:border-rule2 transition-colors disabled:opacity-50"
                    >
                        <RefreshCw size={14} className={regeneratingCopy ? 'animate-spin' : ''} />
                        {regeneratingCopy ? 'generating new ideas…' : 'refresh: new title & description'}
                    </button>
                    {regenerateCopyError && (
                        <p className="text-xs text-danger flex items-center gap-1.5">
                            <AlertCircle size={13} className="shrink-0" /> {regenerateCopyError}
                        </p>
                    )}

                    <div>
                        <div className="flex items-center justify-between gap-2 mb-1.5">
                            <label className="eyebrow">YOUTUBE TITLE</label>
                            <button
                                onClick={() => handleCopy('youtube', displayClip.video_title_for_youtube_short || "Viral Short Video")}
                                aria-label="copy youtube title"
                                className="p-1 rounded-full text-muted hover:text-brass transition-colors shrink-0"
                            >
                                {copied === 'youtube' ? <Check size={14} className="text-ok" /> : <Copy size={14} />}
                            </button>
                        </div>
                        <p className="text-sm text-ink2 select-all break-words bg-paper rounded-input p-3 border border-rule">
                            {displayClip.video_title_for_youtube_short || "Viral Short Video"}
                        </p>
                    </div>

                    <div>
                        <div className="flex items-center justify-between gap-2 mb-1.5">
                            <label className="eyebrow">TIKTOK · IG CAPTION</label>
                            <button
                                onClick={() => handleCopy('caption', displayClip.video_description_for_tiktok || displayClip.video_description_for_instagram)}
                                aria-label="copy caption"
                                className="p-1 rounded-full text-muted hover:text-brass transition-colors shrink-0"
                            >
                                {copied === 'caption' ? <Check size={14} className="text-ok" /> : <Copy size={14} />}
                            </button>
                        </div>
                        <p className="text-sm text-ink2 select-all break-words bg-paper rounded-input p-3 border border-rule whitespace-pre-wrap">
                            {displayClip.video_description_for_tiktok || displayClip.video_description_for_instagram}
                        </p>
                    </div>
                </div>
            </Modal>

            {/* Post Modal */}
            <Modal
                isOpen={showModal}
                onClose={() => setShowModal(false)}
                eyebrow="PUBLISH"
                title="post clip"
                size="md"
                footer={
                    noAccountsConnected ? (
                        <button onClick={handleConnectAccounts} className="btn-primary w-full">
                            <Link2 size={16} /> connect accounts
                        </button>
                    ) : (
                        <button
                            onClick={handlePost}
                            disabled={posting || !canPost}
                            className="btn-primary w-full"
                        >
                            {posting ? <><Loader2 size={16} className="animate-spin" /> {isScheduling ? 'scheduling…' : 'publishing…'}</> : <><Share2 size={16} /> {isScheduling ? 'schedule post' : 'publish now'}</>}
                        </button>
                    )
                }
            >
                {!canPost && (
                    <div className="mb-4 px-3 py-2 rounded-input text-xs text-warn bg-[color-mix(in_oklab,var(--color-warn)_10%,transparent)] flex items-start gap-2">
                        <AlertCircle size={14} className="mt-0.5 shrink-0" />
                        <div className="lowercase">configure api key in settings first.</div>
                    </div>
                )}

                {noAccountsConnected && (
                    <div className="mb-4 px-3 py-2 rounded-input text-xs text-warn bg-[color-mix(in_oklab,var(--color-warn)_10%,transparent)] flex items-start gap-2">
                        <AlertCircle size={14} className="mt-0.5 shrink-0" />
                        <div className="lowercase">no social accounts connected yet — link tiktok, instagram or youtube to publish this clip.</div>
                    </div>
                )}

                {/* Both the title/description fields below and the schedule
                    button are downstream of this: on a tiktok draft neither
                    travels. See TikTokDraftNotice. */}
                {platforms.tiktok && <TikTokDraftNotice />}

                <div className="space-y-4">
                    {/* Title & Description */}
                    <div>
                        <label className="eyebrow block mb-1.5">TITLE</label>
                        <input
                            type="text"
                            value={postTitle}
                            onChange={(e) => setPostTitle(e.target.value)}
                            className="input-field"
                            placeholder="enter a catchy title…"
                        />
                    </div>

                    <div>
                        <label className="eyebrow block mb-1.5">CAPTION</label>
                        <textarea
                            value={postDescription}
                            onChange={(e) => setPostDescription(e.target.value)}
                            rows={4}
                            className="input-field resize-none"
                            placeholder="write a caption for your post…"
                        />
                        <p className="readout mt-1.5">
                            leave title & caption untouched to send each platform its own caption + niche hashtags
                        </p>
                    </div>

                    {/* When — one click, the date picker only for "pick…". */}
                    <div>
                        <label className="eyebrow block mb-2">WHEN</label>
                        <SegmentedControl
                            options={WHEN_OPTIONS}
                            value={whenChoice}
                            onChange={setWhenChoice}
                            columns={4}
                            size="sm"
                        />
                        {whenChoice === 'custom' && (
                            <input
                                type="datetime-local"
                                value={scheduleDate}
                                onChange={(e) => setScheduleDate(e.target.value)}
                                className="input-field mt-2 [color-scheme:dark] animate-fade"
                            />
                        )}
                    </div>

                    {/* Niche — real hashtags on the YouTube title + TikTok caption. */}
                    <div>
                        <label className="eyebrow block mb-2">NICHE</label>
                        <NichePicker value={postNiche} onChange={setPostNiche} />
                    </div>

                    {/* Platforms */}
                    <div>
                        <label className="eyebrow block mb-2">PLATFORMS</label>
                        <SegmentedControl
                            multi
                            columns={3}
                            options={platformOptions}
                            value={Object.keys(platforms).filter(k => platforms[k])}
                            onChange={(arr) => setPlatforms({
                                tiktok: arr.includes('tiktok'),
                                instagram: arr.includes('instagram'),
                                youtube: arr.includes('youtube'),
                            })}
                        />
                    </div>

                    {postResult && (
                        <div className={postResult.success ? 'badge-ok' : 'badge-danger'}>
                            {postResult.success ? <Check size={12} className="shrink-0" /> : <AlertCircle size={12} className="shrink-0" />}
                            {postResult.msg}
                        </div>
                    )}
                </div>
            </Modal>

            <SubtitleModal
                isOpen={showSubtitleModal}
                onClose={() => setShowSubtitleModal(false)}
                onGenerate={handleSubtitle}
                onApplyAll={onBulkSubtitle ? async (options) => {
                    await onBulkSubtitle(options);
                    setShowSubtitleModal(false);
                } : undefined}
                onRemove={handleRemoveSubtitles}
                bulkCount={clipCount}
                bulkProgress={bulkProgress}
                isProcessing={isSubtitling || (bulkProgress?.running ?? false)}
                videoUrl={originalVideoUrl}
                jobId={jobId}
                clipIndex={index}
                existingHook={activeLayers.hook}
                geminiApiKey={geminiApiKey}
            />

            <HookModal
                isOpen={showHookModal}
                onClose={() => setShowHookModal(false)}
                onGenerate={handleHook}
                isProcessing={isHooking}
                videoUrl={originalVideoUrl}
                initialText={clip.viral_hook_text}
                durationInSeconds={clip.end && clip.start ? clip.end - clip.start : 30}
                existingSubtitles={activeLayers.subtitles}
                hasCaptions={!!activeLayers.subtitles || /(^|_)subtitled_/.test(serverVideoFile || '')}
                serverRender={hasServerBurns}
                burnedHook={burnedHook}
                onRemove={burnedHook ? handleRemoveHook : null}
            />

            <TranslateModal
                isOpen={showTranslateModal}
                onClose={() => setShowTranslateModal(false)}
                onTranslate={handleTranslate}
                isProcessing={isTranslating}
                videoUrl={currentVideoUrl}
                hasApiKey={!!elevenLabsKey}
            />

            {showWatermarkModal && (
                <WatermarkModal
                    onClose={() => setShowWatermarkModal(false)}
                    onContinue={downloadClip}
                />
            )}

            <NichePromptModal
                isOpen={!!nichePrompt}
                onClose={() => setNichePrompt(null)}
                defaultValue={nichePrompt?.defaultValue}
                message={nichePrompt?.message}
                onSkip={nichePrompt?.onSkip}
                onConfirm={nichePrompt?.onConfirm}
            />

        </div>
    );
}
