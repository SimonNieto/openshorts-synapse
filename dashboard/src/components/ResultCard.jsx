import React, { useState, useEffect } from 'react';
import { Download, Share2, Instagram, Youtube, Video, AlertCircle, Loader2, Copy, Check, Wand2, Type, Languages, FileText, Link2, Scissors, Crosshair, Sparkles, RefreshCw, Film, ChevronDown, Image as ImageIcon } from 'lucide-react';
import { getApiUrl } from '../config';
import { apiFetch, apiJson } from '../lib/api';
import SubtitleModal from './SubtitleModal';
import HookModal from './HookModal';
import BrollModal from './BrollModal';
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

// The card's edit tools: one quiet, monochrome tool row. Colour stays on the
// single main action (Publish); a tool only lights up in words, never in hue.
const TOOL_BTN = 'group/tool flex items-center gap-2 min-h-[40px] [@media(pointer:coarse)]:min-h-[44px] px-2.5 py-2 rounded-input border border-rule bg-paper2 text-left text-[13px] leading-tight text-ink2 hover:text-ink hover:border-rule2 hover:bg-paper3 transition-colors disabled:opacity-45 disabled:cursor-not-allowed';
const TOOL_ICON = 'shrink-0 text-muted group-hover/tool:text-ink transition-colors';
// Icon-only utility buttons (copy): 32px on a mouse, 44px under a finger.
const ICON_BTN = 'inline-flex items-center justify-center w-8 h-8 [@media(pointer:coarse)]:w-11 [@media(pointer:coarse)]:h-11 rounded-input text-muted hover:text-ink hover:bg-paper3 transition-colors';
// Form labels: mono micro labels in ink, not in the signal colour.
const FIELD_LABEL = 'readout text-ink2 block mb-2';

const PLATFORM_OPTIONS = [
    { value: 'tiktok', label: 'TikTok', icon: <Video size={16} /> },
    { value: 'instagram', label: 'Instagram', icon: <Instagram size={16} /> },
    { value: 'youtube', label: 'YouTube', icon: <Youtube size={16} /> },
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
    { value: 'now', label: 'Now' },
    { value: 'tonight', label: 'Tonight', hint: '19:00' },
    { value: 'tomorrow', label: 'Tomorrow', hint: '12:00' },
    { value: 'custom', label: 'Pick…' },
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
    const [showBrollModal, setShowBrollModal] = useState(false);
    const [brollPending, setBrollPending] = useState(!!clip.broll_pending);
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
        ? PLATFORM_OPTIONS.map((o) => (connectedPlatforms.includes(o.value) ? o : { ...o, disabled: true, hint: 'Not connected' }))
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

    // ---- Presentation only: nothing below changes what the card does. ----
    // Stable ids so labels, groups and the style picker can point at each other.
    const uid = React.useId();
    const titleId = `${uid}-title`;
    const copyId = `${uid}-copy`;
    const toolsId = `${uid}-tools`;
    const stylesId = `${uid}-styles`;
    const descTitleId = `${uid}-desc-title`;
    const descCaptionId = `${uid}-desc-caption`;
    const postTitleId = `${uid}-post-title`;
    const postCaptionId = `${uid}-post-caption`;
    const postCaptionHintId = `${uid}-post-caption-hint`;
    const postWhenId = `${uid}-post-when`;
    const postDateId = `${uid}-post-date`;
    const postNicheId = `${uid}-post-niche`;
    const postNicheHintId = `${uid}-post-niche-hint`;
    const postPlatformsId = `${uid}-post-platforms`;

    // The viral-style picker is a disclosure: Escape closes it and hands focus
    // back to the button that opened it.
    const styleTriggerRef = React.useRef(null);
    const onStylePickerKeyDown = (e) => {
        if (e.key === 'Escape' && stylePicker) {
            e.stopPropagation();
            setStylePicker(false);
            styleTriggerRef.current?.focus();
        }
    };

    const hasScore = Number.isFinite(clip.predicted_score);
    const scorePct = hasScore ? Math.max(0, Math.min(100, clip.predicted_score)) : 0;
    const youtubeTitle = displayClip.video_title_for_youtube_short || "Viral Short Video";
    const socialCaption = displayClip.video_description_for_tiktok || displayClip.video_description_for_instagram;

    // One polite announcement per running job; the buttons say the same thing.
    const busyStatus = isEditing ? 'Applying viral edits…'
        : isSubtitling ? 'Updating subtitles…'
            : isHooking ? 'Updating the hook…'
                : isTranslating ? 'Dubbing the voice…'
                    : downloadPct !== null ? 'Downloading the clip…'
                        : '';

    return (
        <article
            aria-labelledby={titleId}
            className="card overflow-hidden animate-fade"
            style={{ animationDelay: `${index * 0.1}s` }}
        >
            {/* The card lives in grids of any width (one wide column while a
                job runs, two or three once it is done), so it reads its OWN
                width with a container query, not the viewport's:
                  narrow  (< 32rem)  plate, then text, then tools, stacked;
                  medium  (32–52rem) plate | text, tools full width below;
                  wide    (≥ 52rem)  plate | text over tools.
                The query root wraps the card body only: a size container
                would trap the position: fixed of the modals further down. */}
            <div className="[container-type:inline-size]">
                <div className="grid grid-cols-1 [@container(min-width:32rem)]:grid-cols-[auto_minmax(0,1fr)] [@container(min-width:52rem)]:grid-rows-[auto_1fr]">

                    {/* The plate: the clip on black, a hairline frame, a mono caption. */}
                    <figure className="min-w-0 p-4 bg-paper border-b border-rule [@container(min-width:32rem)]:w-[13rem] [@container(min-width:32rem)]:border-b-0 [@container(min-width:32rem)]:border-r [@container(min-width:40rem)]:w-[15rem] [@container(min-width:52rem)]:w-[16rem] [@container(min-width:52rem)]:row-span-2 [@container(min-width:72rem)]:w-[18rem]">
                        {/* Stacked (narrow card), a full-width 9:16 preview is
                            ~640px tall on its own and pushes the title and every
                            action off-screen: cap it to the viewport height and
                            centre it, without letterboxing the clip. */}
                        <div className="relative mx-auto w-full max-w-[min(calc(64vh*0.5625),18rem)] [@container(min-width:32rem)]:max-w-none aspect-[9/16] bg-black border border-rule2 rounded-input overflow-hidden">
                            <video
                                ref={videoRef}
                                // #t=0.1 makes the browser paint the first real frame
                                // instead of a black box until the clip is played.
                                src={playbackUrl && !playbackUrl.includes('#') ? `${playbackUrl}#t=0.1` : playbackUrl}
                                preload="metadata"
                                controls
                                aria-label={`Clip ${index + 1} preview`}
                                className="absolute inset-0 w-full h-full object-contain"
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

                            {/* Auto edit / viral style running on this clip */}
                            {isEditing && (
                                <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 p-4 text-center bg-paper/85">
                                    <Loader2 size={24} className="animate-spin text-ink" aria-hidden="true" />
                                    <span className="text-sm font-medium text-ink">Editing with AI…</span>
                                    <span className="readout">Viral edits · zooms</span>
                                </div>
                            )}
                        </div>

                        <figcaption className="readout mt-3 flex flex-wrap items-center justify-center gap-x-2 gap-y-1 [@container(min-width:32rem)]:justify-start">
                            {/* Stays the clip's own number, not its rank: the cards
                                are ordered by score, but this is what the downloaded
                                file is called (clip-N.mp4) and what every api call
                                indexes. */}
                            <span className="text-ink2">Clip {index + 1}</span>
                            {durationReadout && (
                                <>
                                    <span aria-hidden="true">·</span>
                                    <span><span className="sr-only">Duration </span>{durationReadout}</span>
                                </>
                            )}
                            {resolution && (
                                <>
                                    <span aria-hidden="true">·</span>
                                    <span><span className="sr-only">Resolution </span>{resolution}</span>
                                </>
                            )}
                        </figcaption>
                    </figure>

                    {/* The text side: title + score, the post copy, then the one main action (Publish) and Download. */}
                    <div className="min-w-0 p-4 [@container(min-width:32rem)]:p-5 flex flex-col gap-5">
                        <header className="flex items-start gap-4">
                            <h3
                                id={titleId}
                                className="flex-1 min-w-0 text-lg [@container(min-width:52rem)]:text-xl font-semibold tracking-[-0.02em] leading-snug text-ink break-words line-clamp-3"
                                title={displayClip.video_title_for_youtube_short}
                            >
                                {displayClip.video_title_for_youtube_short || 'Untitled clip'}
                            </h3>
                            {/* A bare number reads as a duration, a position,
                                anything: it names itself and carries its scale. */}
                            {hasScore && (
                                <div
                                    className="shrink-0 text-right"
                                    title="Synapse AI's prediction of how well this clip will perform, from 0 to 100"
                                >
                                    <p className="readout whitespace-nowrap">Viral score</p>
                                    <p className="mt-1.5 whitespace-nowrap text-ink leading-none">
                                        <span className="font-quote text-[2.75rem]">{clip.predicted_score}</span>
                                        <span className="font-mono text-xs text-muted" aria-hidden="true">/100</span>
                                        <span className="sr-only"> out of 100</span>
                                    </p>
                                    <div className="mt-2 ml-auto h-px w-16 bg-[color:var(--color-rule-2)]" aria-hidden="true">
                                        <div className="h-px bg-ink" style={{ width: `${scorePct}%` }} />
                                    </div>
                                </div>
                            )}
                        </header>

                        {/* Post copy (compact) — the full text lives in the modal */}
                        <div role="group" aria-labelledby={copyId} className="min-w-0">
                            <div className="flex items-center justify-between gap-3 mb-1">
                                <p id={copyId} className="readout">Post copy</p>
                                <button
                                    type="button"
                                    onClick={() => setShowDescModal(true)}
                                    className="inline-flex items-center gap-1.5 min-h-[32px] [@media(pointer:coarse)]:min-h-[44px] text-xs text-cobalt hover:text-ink transition-colors"
                                >
                                    <FileText size={13} aria-hidden="true" /> Full descriptions
                                </button>
                            </div>
                            <dl className="border-y border-rule divide-y divide-rule">
                                <div className="flex items-center gap-3 py-1 min-w-0">
                                    <dt className="readout w-[5.75rem] shrink-0">YouTube</dt>
                                    <dd className="flex-1 min-w-0 text-[13px] text-ink2 truncate">{youtubeTitle}</dd>
                                    <dd className="shrink-0">
                                        <button
                                            type="button"
                                            onClick={() => handleCopy('youtube', youtubeTitle)}
                                            aria-label={copied === 'youtube' ? 'YouTube title copied' : 'Copy YouTube title'}
                                            className={ICON_BTN}
                                        >
                                            {copied === 'youtube' ? <Check size={14} className="text-ok" aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
                                        </button>
                                    </dd>
                                </div>
                                <div className="flex items-center gap-3 py-1 min-w-0">
                                    <dt className="readout w-[5.75rem] shrink-0">TikTok · IG</dt>
                                    <dd className="flex-1 min-w-0 text-[13px] text-ink2 truncate">{socialCaption}</dd>
                                    <dd className="shrink-0">
                                        <button
                                            type="button"
                                            onClick={() => handleCopy('caption', socialCaption)}
                                            aria-label={copied === 'caption' ? 'Caption copied' : 'Copy TikTok and Instagram caption'}
                                            className={ICON_BTN}
                                        >
                                            {copied === 'caption' ? <Check size={14} className="text-ok" aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
                                        </button>
                                    </dd>
                                </div>
                            </dl>
                        </div>

                        {/* The one main action (Publish), then Download. */}
                        <div className="mt-auto space-y-2.5">
                            <div className="flex flex-wrap gap-2">
                                <button
                                    type="button"
                                    onClick={() => setShowModal(true)}
                                    className="btn-accent flex-1 basis-36"
                                >
                                    <Share2 size={16} className="shrink-0" aria-hidden="true" /> Publish
                                </button>
                                <button
                                    type="button"
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
                                    className="btn-ghost flex-1 basis-36"
                                >
                                    <Download size={16} className="shrink-0" aria-hidden="true" />
                                    {downloadPct === null ? 'Download' : `Downloading ${downloadPct}%`}
                                </button>
                            </div>
                            {downloadPct !== null && (
                                <div
                                    role="progressbar"
                                    aria-label="Download progress"
                                    aria-valuemin={0}
                                    aria-valuemax={100}
                                    aria-valuenow={downloadPct}
                                    className="h-0.5 w-full overflow-hidden rounded-full bg-[color:var(--color-rule-2)]"
                                >
                                    <div className="h-full bg-ink transition-[width] duration-200" style={{ width: `${downloadPct}%` }} />
                                </div>
                            )}
                        </div>
                        <p className="sr-only" aria-live="polite">{busyStatus}</p>
                    </div>

                    {/* Edit tools: one labelled group, monochrome. Under the
                        main column on a wide card, full width under the plate
                        on a medium one, last in the stack on a narrow one. */}
                    <div className="min-w-0 px-4 pb-4 border-rule [@container(min-width:32rem)]:col-span-2 [@container(min-width:32rem)]:p-5 [@container(min-width:32rem)]:border-t [@container(min-width:52rem)]:col-span-1 [@container(min-width:52rem)]:col-start-2 [@container(min-width:52rem)]:border-t-0 [@container(min-width:52rem)]:pt-0">
                        <div role="group" aria-labelledby={toolsId} className="pt-4 border-t border-rule [@container(min-width:32rem)]:pt-0 [@container(min-width:32rem)]:border-t-0 [@container(min-width:52rem)]:pt-4 [@container(min-width:52rem)]:border-t">
                            <p id={toolsId} className="readout mb-2">Edit</p>
                            <div className="grid gap-1.5 grid-cols-[repeat(auto-fill,minmax(8.25rem,1fr))]">
                                {onEditClip && (
                                    <button type="button" onClick={() => onEditClip(index)} className={TOOL_BTN}>
                                        <Scissors size={16} className={TOOL_ICON} aria-hidden="true" />
                                        Edit clip
                                    </button>
                                )}

                                {onReframeClip && (
                                    <button type="button" onClick={() => onReframeClip(index)} className={TOOL_BTN}>
                                        <Crosshair size={16} className={TOOL_ICON} aria-hidden="true" />
                                        Reframe
                                    </button>
                                )}

                                <button
                                    type="button"
                                    onClick={() => setShowSubtitleModal(true)}
                                    disabled={isSubtitling}
                                    className={TOOL_BTN}
                                >
                                    {isSubtitling
                                        ? <Loader2 size={16} className="shrink-0 animate-spin text-ink" aria-hidden="true" />
                                        : <Type size={16} className={TOOL_ICON} aria-hidden="true" />}
                                    {isSubtitling ? 'Adding…' : 'Subtitles'}
                                </button>

                                <button
                                    type="button"
                                    onClick={() => setShowHookModal(true)}
                                    disabled={isHooking}
                                    className={TOOL_BTN}
                                >
                                    {isHooking
                                        ? <Loader2 size={16} className="shrink-0 animate-spin text-ink" aria-hidden="true" />
                                        : <Wand2 size={16} className={TOOL_ICON} aria-hidden="true" />}
                                    {isHooking ? 'Adding…' : 'Hook'}
                                </button>

                                {(clip.broll || []).some((it) => it.image) && (
                                    <button
                                        type="button"
                                        onClick={() => setShowBrollModal(true)}
                                        className={`${TOOL_BTN} ${brollPending ? '!border-ink !text-ink font-medium' : ''}`}
                                        title={brollPending ? 'Images prepared: check them, then cut them in' : "Edit this clip's images"}
                                    >
                                        <ImageIcon size={16} className={brollPending ? 'shrink-0 text-ink' : TOOL_ICON} aria-hidden="true" />
                                        <span className="min-w-0">{brollPending ? 'Check images' : 'Images'}</span>
                                        {brollPending && <span className="ml-auto h-1.5 w-1.5 shrink-0 rounded-full bg-ink" aria-hidden="true" />}
                                    </button>
                                )}

                                <button
                                    type="button"
                                    onClick={() => setShowTranslateModal(true)}
                                    disabled={isTranslating}
                                    className={TOOL_BTN}
                                >
                                    {isTranslating
                                        ? <Loader2 size={16} className="shrink-0 animate-spin text-ink" aria-hidden="true" />
                                        : <Languages size={16} className={TOOL_ICON} aria-hidden="true" />}
                                    {isTranslating ? 'Dubbing…' : 'Dub voice'}
                                </button>

                                <button
                                    type="button"
                                    onClick={handleAutoEdit}
                                    disabled={isEditing}
                                    className={TOOL_BTN}
                                >
                                    {isEditing
                                        ? <Loader2 size={16} className="shrink-0 animate-spin text-ink" aria-hidden="true" />
                                        : <Sparkles size={16} className={TOOL_ICON} aria-hidden="true" />}
                                    {isEditing ? 'Editing…' : 'Auto edit'}
                                </button>

                                {/* Viral edit styles (viral_fx.py): jump zooms + colour key-word captions. */}
                                <button
                                    ref={styleTriggerRef}
                                    type="button"
                                    onClick={() => setStylePicker((v) => !v)}
                                    onKeyDown={onStylePickerKeyDown}
                                    disabled={isEditing}
                                    aria-expanded={stylePicker}
                                    aria-controls={stylePicker ? stylesId : undefined}
                                    className={`${TOOL_BTN} ${stylePicker ? '!border-rule2 !bg-paper3 !text-ink' : ''}`}
                                    title="Jump zooms + big captions with coloured key words, like viral podcast shorts"
                                >
                                    <Film size={16} className={TOOL_ICON} aria-hidden="true" />
                                    <span className="min-w-0">Viral style</span>
                                    <ChevronDown
                                        size={14}
                                        className={`ml-auto shrink-0 text-muted transition-transform ${stylePicker ? 'rotate-180' : ''}`}
                                        aria-hidden="true"
                                    />
                                </button>
                                {stylePicker && (
                                    <div
                                        id={stylesId}
                                        role="group"
                                        aria-label="Viral styles"
                                        onKeyDown={onStylePickerKeyDown}
                                        className="col-span-full tray p-3 animate-fade"
                                    >
                                        <p className="text-xs text-muted leading-relaxed mb-2.5">
                                            Jump zooms and big captions with coloured key words. Replaces this clip's captions.
                                        </p>
                                        <div className="grid gap-1.5 grid-cols-[repeat(auto-fill,minmax(11rem,1fr))]">
                                            <button
                                                type="button"
                                                onClick={() => { styleTriggerRef.current?.focus(); handleViralStyle('natural'); }}
                                                className="flex flex-col items-start gap-1 rounded-input border border-rule bg-paper2 px-3 py-2.5 text-left hover:border-rule2 hover:bg-paper transition-colors"
                                            >
                                                <span className="text-sm font-medium text-ink">Natural</span>
                                                <span className="text-xs text-muted leading-snug">2–3 plain white words, calm reframes at sentence ends — like the big podcast channels.</span>
                                            </button>
                                            <button
                                                type="button"
                                                onClick={() => { styleTriggerRef.current?.focus(); handleViralStyle('premium'); }}
                                                className="flex flex-col items-start gap-1 rounded-input border border-rule bg-paper2 px-3 py-2.5 text-left hover:border-rule2 hover:bg-paper transition-colors"
                                            >
                                                <span className="text-sm font-medium text-ink">Premium</span>
                                                <span className="text-xs text-muted leading-snug">The natural look, set in Montserrat ExtraBold.</span>
                                            </button>
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>

                        {/* Error Message */}
                        {editError && (
                            <div role="alert" className="mt-3 flex items-start gap-2 rounded-input border border-danger/35 bg-danger/10 px-3 py-2 text-[13px] text-ink2">
                                <AlertCircle size={15} className="mt-0.5 shrink-0 text-danger" aria-hidden="true" />
                                <span className="min-w-0 break-words">{editError}</span>
                            </div>
                        )}
                    </div>
                </div>
            </div>

            {/* Descriptions Modal */}
            <Modal
                isOpen={showDescModal}
                onClose={() => setShowDescModal(false)}
                eyebrow="Generated copy"
                title="Descriptions"
                size="md"
                footer={
                    <div className="space-y-2.5">
                        {regenerateCopyError && (
                            <p role="alert" className="flex items-start gap-1.5 text-[13px] text-danger">
                                <AlertCircle size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
                                <span className="min-w-0 break-words">{regenerateCopyError}</span>
                            </p>
                        )}
                        <button
                            type="button"
                            onClick={handleRegenerateCopy}
                            disabled={regeneratingCopy}
                            className="btn-ghost w-full"
                        >
                            <RefreshCw size={15} className={regeneratingCopy ? 'animate-spin' : ''} aria-hidden="true" />
                            {regeneratingCopy ? 'Writing new ideas…' : 'New title and description'}
                        </button>
                        <p className="sr-only" aria-live="polite">
                            {regeneratingCopy ? 'Writing a new title and description…' : ''}
                        </p>
                    </div>
                }
            >
                <div className="space-y-5">
                    <div role="group" aria-labelledby={descTitleId}>
                        <div className="flex items-center justify-between gap-2 mb-2">
                            <p id={descTitleId} className="readout text-ink2">YouTube title</p>
                            <button
                                type="button"
                                onClick={() => handleCopy('youtube', youtubeTitle)}
                                aria-label={copied === 'youtube' ? 'YouTube title copied' : 'Copy YouTube title'}
                                className="btn-quiet px-2.5 py-1 text-xs"
                            >
                                {copied === 'youtube'
                                    ? <><Check size={13} className="text-ok" aria-hidden="true" /> Copied</>
                                    : <><Copy size={13} aria-hidden="true" /> Copy</>}
                            </button>
                        </div>
                        <p className="tray p-3 text-sm text-ink select-all break-words">
                            {youtubeTitle}
                        </p>
                    </div>

                    <div role="group" aria-labelledby={descCaptionId}>
                        <div className="flex items-center justify-between gap-2 mb-2">
                            <p id={descCaptionId} className="readout text-ink2">TikTok · Instagram caption</p>
                            <button
                                type="button"
                                onClick={() => handleCopy('caption', socialCaption)}
                                aria-label={copied === 'caption' ? 'Caption copied' : 'Copy caption'}
                                className="btn-quiet px-2.5 py-1 text-xs"
                            >
                                {copied === 'caption'
                                    ? <><Check size={13} className="text-ok" aria-hidden="true" /> Copied</>
                                    : <><Copy size={13} aria-hidden="true" /> Copy</>}
                            </button>
                        </div>
                        <p className="tray p-3 text-sm text-ink select-all break-words whitespace-pre-wrap">
                            {socialCaption}
                        </p>
                    </div>
                </div>
            </Modal>

            {/* Post Modal */}
            <Modal
                isOpen={showModal}
                onClose={() => setShowModal(false)}
                eyebrow="Publish"
                title="Post this clip"
                size="md"
                footer={
                    noAccountsConnected ? (
                        <button type="button" onClick={handleConnectAccounts} className="btn-primary w-full">
                            <Link2 size={16} aria-hidden="true" /> Connect accounts
                        </button>
                    ) : (
                        <button
                            type="button"
                            onClick={handlePost}
                            disabled={posting || !canPost}
                            className="btn-accent w-full"
                        >
                            {posting
                                ? <><Loader2 size={16} className="animate-spin" aria-hidden="true" /> {isScheduling ? 'Scheduling…' : 'Publishing…'}</>
                                : <><Share2 size={16} aria-hidden="true" /> {isScheduling ? 'Schedule post' : 'Publish now'}</>}
                        </button>
                    )
                }
            >
                {!canPost && (
                    <div className="mb-4 flex items-start gap-2.5 rounded-input border border-warn/30 bg-warn/10 px-3 py-2.5 text-[13px] leading-relaxed text-ink2">
                        <AlertCircle size={15} className="mt-0.5 shrink-0 text-warn" aria-hidden="true" />
                        <p>Set your Upload-Post API key in Settings first.</p>
                    </div>
                )}

                {noAccountsConnected && (
                    <div className="mb-4 flex items-start gap-2.5 rounded-input border border-warn/30 bg-warn/10 px-3 py-2.5 text-[13px] leading-relaxed text-ink2">
                        <AlertCircle size={15} className="mt-0.5 shrink-0 text-warn" aria-hidden="true" />
                        <p>No social account is connected yet. Link TikTok, Instagram or YouTube to publish this clip.</p>
                    </div>
                )}

                {/* Both the title/description fields below and the schedule
                    button are downstream of this: on a tiktok draft neither
                    travels. See TikTokDraftNotice. */}
                {platforms.tiktok && <TikTokDraftNotice />}

                <div className="space-y-5">
                    {/* Title & Description */}
                    <div>
                        <label htmlFor={postTitleId} className={FIELD_LABEL}>Title</label>
                        <input
                            id={postTitleId}
                            type="text"
                            value={postTitle}
                            onChange={(e) => setPostTitle(e.target.value)}
                            className="input-field"
                            placeholder="A catchy title…"
                        />
                    </div>

                    <div>
                        <label htmlFor={postCaptionId} className={FIELD_LABEL}>Caption</label>
                        <textarea
                            id={postCaptionId}
                            aria-describedby={postCaptionHintId}
                            value={postDescription}
                            onChange={(e) => setPostDescription(e.target.value)}
                            rows={4}
                            className="input-field resize-none"
                            placeholder="Write a caption for your post…"
                        />
                        <p id={postCaptionHintId} className="mt-1.5 text-xs leading-relaxed text-muted">
                            Leave the title and caption untouched to send each platform its own caption and niche hashtags.
                        </p>
                    </div>

                    {/* When — one click, the date picker only for "Pick…". */}
                    <div role="group" aria-labelledby={postWhenId}>
                        <p id={postWhenId} className={FIELD_LABEL}>When</p>
                        <SegmentedControl
                            options={WHEN_OPTIONS}
                            value={whenChoice}
                            onChange={setWhenChoice}
                            columns={4}
                            size="sm"
                        />
                        {whenChoice === 'custom' && (
                            <div className="mt-2 animate-fade">
                                <label htmlFor={postDateId} className="sr-only">Date and time</label>
                                <input
                                    id={postDateId}
                                    type="datetime-local"
                                    value={scheduleDate}
                                    onChange={(e) => setScheduleDate(e.target.value)}
                                    className="input-field"
                                />
                            </div>
                        )}
                    </div>

                    {/* Niche — real hashtags on the YouTube title + TikTok caption. */}
                    <div role="group" aria-labelledby={postNicheId} aria-describedby={postNicheHintId}>
                        <p id={postNicheId} className={FIELD_LABEL}>Niche</p>
                        <NichePicker value={postNiche} onChange={setPostNiche} />
                        <p id={postNicheHintId} className="mt-1.5 text-xs leading-relaxed text-muted">
                            Adds real hashtags to the YouTube title and the TikTok caption.
                        </p>
                    </div>

                    {/* Platforms */}
                    <div role="group" aria-labelledby={postPlatformsId}>
                        <p id={postPlatformsId} className={FIELD_LABEL}>Platforms</p>
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
                </div>

                <div aria-live="polite">
                    {postResult && (
                        <div
                            role={postResult.success ? undefined : 'alert'}
                            className={`mt-5 flex items-start gap-2 rounded-input border px-3 py-2.5 text-[13px] text-ink2 ${postResult.success ? 'border-ok/30 bg-ok/10' : 'border-danger/35 bg-danger/10'}`}
                        >
                            {postResult.success
                                ? <Check size={15} className="mt-0.5 shrink-0 text-ok" aria-hidden="true" />
                                : <AlertCircle size={15} className="mt-0.5 shrink-0 text-danger" aria-hidden="true" />}
                            <span className="min-w-0 break-words">{postResult.msg}</span>
                        </div>
                    )}
                </div>
            </Modal>

            <BrollModal
                isOpen={showBrollModal}
                onClose={() => setShowBrollModal(false)}
                jobId={jobId}
                index={index}
                clip={clip}
                profileId={plusProfileId}
                onApplied={(data) => {
                    setBrollPending(false);
                    if (data.new_video_url) {
                        setCurrentVideoUrl(getApiUrl(data.new_video_url));
                        setServerVideoFile(data.new_video_url.split('/').pop());
                        if (videoRef.current) videoRef.current.load();
                    }
                }}
            />

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

        </article>
    );
}
