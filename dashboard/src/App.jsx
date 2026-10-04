import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Square, Upload, Sparkles, Youtube, Instagram, Share2, ChevronDown, Check, LayoutDashboard, Settings, Plus, History, X, Terminal, Shield, LayoutGrid, Image, Globe, RotateCcw, Calendar, AlertTriangle, KeyRound, Smartphone, ExternalLink, Copy, CheckCircle2, Loader2, Download, Menu, Lock, Eraser, Hash, Flame, Clapperboard, Rocket, Library, Images } from 'lucide-react';
import KeyInput from './components/KeyInput';
import MediaInput from './components/MediaInput';
import ResultCard from './components/ResultCard';
import { loadSubtitleProfileStore, activeSubtitleProfileSettings } from './components/SubtitleModal';
import ProcessingAnimation from './components/ProcessingAnimation';
import JobProgressBar from './components/JobProgressBar';
import BrainBadge from './components/BrainBadge';
// import Gallery from './components/Gallery';
import ThumbnailStudio from './components/ThumbnailStudio';
import SaaShortsTab from './components/SaaShortsTab';
import UGCGallery from './components/UGCGallery';
import ScheduleWeekModal from './components/ScheduleWeekModal';
import ClipEditor from './components/ClipEditor';
import ReframeEditor from './components/ReframeEditor';
import UsageMeter from './components/UsageMeter';
import TopUpModal from './components/TopUpModal';
import StarBanner from './components/StarBanner';
import PlanChoiceModal from './components/PlanChoiceModal';
import ClipTutorial from './components/ClipTutorial';
import TrialUpgradeModal from './components/TrialUpgradeModal';
import LoginModal from './components/LoginModal';
import TrialGate from './components/TrialGate';
import AdvancedBanner from './components/AdvancedBanner';
import HistoryTab from './components/HistoryTab';
import ReworkerTab from './components/ReworkerTab';
import PublishPlanTab from './components/PublishPlanTab';
import ViralFinderTab from './components/ViralFinderTab';
import StoryTab from './components/StoryTab';
import PlusPanel from './components/PlusPanel';
import NotionLibrary from './components/NotionLibrary';
import BrollGallery from './components/BrollGallery';
import ProfileMenu from './components/ProfileMenu';
import Modal from './components/ui/Modal';
import NichePromptModal from './components/NichePromptModal';
import { loadNicheHistory, pushNicheHistory, rememberNicheProfile } from './lib/nicheHistory';
import { userTimezone } from './lib/postSlots';
import { useAuth } from './contexts/AuthContext';
import { apiFetch, apiJson, QuotaError } from './lib/api';
import { isKeyLog } from './lib/logFilter';
import { track } from './lib/analytics';

// Enhanced "Encryption" using XOR + Base64 with a Salt
// This is better than plain Base64 but still client-side.
const SECRET_KEY = import.meta.env.VITE_ENCRYPTION_KEY || "OpenShorts-Static-Salt-Change-Me";
const ENCRYPTION_PREFIX = "ENC:";

const encrypt = (text) => {
  if (!text) return '';
  try {
    const xor = text.split('').map((c, i) =>
      String.fromCharCode(c.charCodeAt(0) ^ SECRET_KEY.charCodeAt(i % SECRET_KEY.length))
    ).join('');
    return ENCRYPTION_PREFIX + btoa(xor);
  } catch (e) {
    console.error("Encryption failed", e);
    return text;
  }
};

const decrypt = (text) => {
  if (!text) return '';
  if (text.startsWith(ENCRYPTION_PREFIX)) {
    try {
      const raw = text.slice(ENCRYPTION_PREFIX.length);
      // Check if it's plain base64 or our custom XOR (simple try)
      const xor = atob(raw);
      const result = xor.split('').map((c, i) =>
        String.fromCharCode(c.charCodeAt(0) ^ SECRET_KEY.charCodeAt(i % SECRET_KEY.length))
      ).join('');
      return result;
    } catch (e) {
      // Fallback if decryption fails (might be old plain text)
      return '';
    }
  }
  // Backward compatibility: If no prefix, assume old plain text (or return empty if you want to force re-login)
  // For migration: Return text as is, so it populates the field, and next save will encrypt it.
  return text;
};

// Simple TikTok icon sine Lucide might not have it or it varies
const TikTokIcon = ({ size = 16, className = "" }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className} aria-hidden="true" focusable="false">
    <path d="M19.589 6.686a4.793 4.793 0 0 1-3.77-4.245V2h-3.445v13.672a2.896 2.896 0 0 1-5.201 1.743l-.002-.001.002.001a2.895 2.895 0 0 1 3.183-4.51v-3.5a6.329 6.329 0 0 0-5.394 10.692 6.33 6.33 0 0 0 10.857-4.424V8.687a8.182 8.182 0 0 0 4.773 1.526V6.79a4.831 4.831 0 0 1-1.003-.104z" />
  </svg>
);

// Cloud accounts get an auto-generated opaque id (os_<hash>) as username —
// meaningless to the user, so the selector shows connected networks instead.
const isAutoProfileId = (username) => /^os_[0-9a-f]/i.test(username || "");

const formatRetention = (seconds) => {
  if (seconds >= 86400) return `${Math.round(seconds / 86400)} day${seconds >= 172800 ? 's' : ''}`;
  if (seconds >= 3600) return `${Math.round(seconds / 3600)} hour${seconds >= 7200 ? 's' : ''}`;
  return `${Math.max(1, Math.round(seconds / 60))} min`;
};

// The three networks of a profile: lit when connected, dimmed when not. The
// state is also spelled out for screen readers (never icon brightness alone).
const NETWORKS = [['tiktok', 'TikTok'], ['instagram', 'Instagram'], ['youtube', 'YouTube']];
const ProfileNetworkIcons = ({ profile, size = 12 }) => {
  const connected = profile?.connected || [];
  return (
    <span className="flex items-center gap-1.5">
      {NETWORKS.map(([id]) => {
        const NetIcon = id === 'tiktok' ? TikTokIcon : id === 'instagram' ? Instagram : Youtube;
        return (
          <span key={id} className={connected.includes(id) ? 'text-ink' : 'text-muted opacity-40'}>
            <NetIcon size={size} aria-hidden="true" />
          </span>
        );
      })}
      <span className="sr-only">
        {connected.length
          ? `Connected: ${NETWORKS.filter(([id]) => connected.includes(id)).map(([, name]) => name).join(', ')}`
          : 'No network connected'}
      </span>
    </span>
  );
};

const UserProfileSelector = ({ profiles, selectedUserId, onSelect, onConnect }) => {
  const [isOpen, setIsOpen] = useState(false);

  if (!profiles || profiles.length === 0) return null;

  const selectedProfile = profiles.find(p => p.username === selectedUserId) || profiles[0];
  const autoId = isAutoProfileId(selectedProfile?.username);
  const profileName = (p) => (isAutoProfileId(p?.username) ? `Social profile ${profiles.indexOf(p) + 1}` : p?.username);

  return (
    <div className="relative z-50">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        aria-label={`Posting profile: ${profileName(selectedProfile) || 'none selected'}`}
        aria-expanded={isOpen}
        aria-haspopup="true"
        /* Phone: avatar + chevron only. A 180px pill next to the menu button,
           the section title and the minutes meter overflowed a 360px header. */
        className="flex items-center justify-between gap-1.5 bg-paper2 border border-rule2 rounded-input px-2 sm:px-3 min-h-[44px] sm:min-h-[36px] text-sm text-ink2 hover:text-ink hover:border-ink/40 transition-colors sm:min-w-[170px]"
      >
        <span className="flex items-center gap-2 min-w-0">
          <span className="w-6 h-6 rounded-full bg-paper3 border border-rule flex items-center justify-center font-mono text-micro text-ink shrink-0" aria-hidden="true">
            {autoId ? "S" : (selectedProfile?.username?.substring(0, 1).toUpperCase() || "U")}
          </span>
          {autoId ? (
            <span className="hidden sm:flex"><ProfileNetworkIcons profile={selectedProfile} size={13} /></span>
          ) : (
            <span className="hidden sm:block font-medium text-ink truncate max-w-[110px]">{selectedProfile?.username || "Select a profile"}</span>
          )}
        </span>
        <ChevronDown size={14} className={`text-muted transition-transform shrink-0 ${isOpen ? 'rotate-180' : ''}`} aria-hidden="true" />
      </button>

      {isOpen && (
        <div className="absolute top-full mt-2 right-0 w-[min(18rem,calc(100vw-1.5rem))] card-print overflow-hidden animate-fade">
          <p className="readout px-4 pt-3 pb-2">Post as</p>
          <ul className="max-h-60 overflow-y-auto custom-scrollbar">
            {profiles.map((profile) => {
              const selected = selectedUserId === profile.username;
              return (
                <li key={profile.username} className="border-t border-rule">
                  <button
                    type="button"
                    onClick={() => {
                      onSelect(profile.username);
                      setIsOpen(false);
                    }}
                    aria-current={selected ? 'true' : undefined}
                    className={`w-full flex items-center justify-between gap-3 px-4 py-3 min-h-[44px] transition-colors text-left group ${selected ? 'bg-paper3' : 'hover:bg-paper3'}`}
                  >
                    <span className="flex items-center gap-3 min-w-0">
                      <span className="w-8 h-8 rounded-full bg-paper3 flex items-center justify-center font-mono text-micro text-ink border border-rule shrink-0" aria-hidden="true">
                        {isAutoProfileId(profile.username) ? "S" : profile.username.substring(0, 2).toUpperCase()}
                      </span>
                      <span className="min-w-0">
                        <span className="block text-sm font-medium text-ink2 group-hover:text-ink transition-colors truncate">
                          {profileName(profile)}
                        </span>
                        <span className="flex mt-1"><ProfileNetworkIcons profile={profile} size={11} /></span>
                      </span>
                    </span>
                    {selected && <Check size={15} className="text-vermilion shrink-0" aria-hidden="true" />}
                  </button>
                </li>
              );
            })}
          </ul>
          {/* For managed users this dropdown otherwise does nothing (one profile,
              nothing to switch) — its real job is being the door to connecting
              the greyed-out networks it displays. */}
          {onConnect && (
            <button
              type="button"
              onClick={() => { setIsOpen(false); onConnect(); }}
              className="w-full flex items-center gap-2 px-4 py-3 min-h-[44px] text-sm text-ink2 hover:text-ink hover:bg-paper3 transition-colors text-left border-t border-rule"
            >
              <Share2 size={14} className="text-muted" aria-hidden="true" /> Connect or manage accounts
            </button>
          )}
        </div>
      )}
    </div>
  );
};

const SESSION_KEY = 'openshorts_session';
// Matches the self-host JOB_RETENTION_SECONDS default. A restore whose job was
// already purged server-side fails gracefully and clears the saved session.
const SESSION_MAX_AGE = 86400000; // 24 hours

// Mock polling function
const pollJob = async (jobId) => {
  const res = await apiFetch(`/api/status/${jobId}`);
  if (!res.ok) throw new Error('Status check failed');
  return res.json();
};

function App() {
  // Cloud auth/billing session (inert when billing is disabled).
  const { billingEnabled, isManaged, isSignedIn, me, plan, refreshMe, jobRetentionSeconds, localLlm } = useAuth();
  const [showLogin, setShowLogin] = useState(false);
  const [showTopUp, setShowTopUp] = useState(false);
  const [showPlanChoice, setShowPlanChoice] = useState(false);
  const [tutorialPhase, setTutorialPhase] = useState(null); // null | intro | coach | celebrate
  const [showTrialUpgrade, setShowTrialUpgrade] = useState(false);
  const [topUpInfo, setTopUpInfo] = useState({});
  // Durable R2 URLs (per clip index) for the current job — used as a fallback when
  // the ephemeral local /videos/ files have been cleaned up (e.g. after a reload).
  const [durableClips, setDurableClips] = useState({});

  const [apiKey, setApiKey] = useState(localStorage.getItem('gemini_key') || '');
  // Social API State - Load encrypted or plain
  const [uploadPostKey, setUploadPostKey] = useState(() => {
    const stored = localStorage.getItem('uploadPostKey_v3');
    if (stored) return decrypt(stored);
    return '';
  });
  // ElevenLabs API State - Load encrypted
  const [elevenLabsKey, setElevenLabsKey] = useState(() => {
    const stored = localStorage.getItem('elevenLabsKey_v1');
    if (stored) return decrypt(stored);
    return '';
  });

  // fal.ai API State - Load encrypted
  const [falKey, setFalKey] = useState(() => {
    const stored = localStorage.getItem('falKey_v1');
    if (stored) return decrypt(stored);
    return '';
  });

  // Content niche (e.g. "Joe Rogan podcast clips") — not a secret, so plain
  // localStorage, no encrypt/decrypt. Lets hashtag research (niche_hashtags.py)
  // and copy generation target real, on-topic hashtags instead of generic ones.
  const [niche, setNiche] = useState(() => localStorage.getItem('openshorts_niche') || '');
  useEffect(() => { localStorage.setItem('openshorts_niche', niche); }, [niche]);
  const [nicheResearching, setNicheResearching] = useState(false);
  const [nicheHashtags, setNicheHashtags] = useState(null);
  const [nicheError, setNicheError] = useState('');
  const [nicheHistory, setNicheHistory] = useState(() => loadNicheHistory());
  // Server-side (publish_settings.json): the niche's base YouTube tags.
  // Clean hashtags + YouTube tags themselves are always on, no toggle.
  const [nicheTagsTable, setNicheTagsTable] = useState({});
  const [nicheTagsDraft, setNicheTagsDraft] = useState('');
  const [nicheTagsSaved, setNicheTagsSaved] = useState(false);
  const applyPublishSettings = (d) => {
    setNicheTagsTable(d.niche_tags || {});
  };
  useEffect(() => {
    apiJson('/api/publish-settings').then(applyPublishSettings).catch(() => {});
  }, []);
  useEffect(() => {
    setNicheTagsDraft((nicheTagsTable[niche.trim().toLowerCase()] || []).join(', '));
    setNicheTagsSaved(false);
  }, [niche, nicheTagsTable]);
  const savePublishSettings = async (patch) => {
    try {
      applyPublishSettings(await apiJson('/api/publish-settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      }));
      return true;
    } catch (_) { return false; }
  };
  // Asked before every download — the hashtag bundling needs a niche and
  // should never silently reuse whatever was used for a different clip/job.
  const [showNichePrompt, setShowNichePrompt] = useState(false);

  const [uploadUserId, setUploadUserId] = useState(() => localStorage.getItem('uploadUserId') || '');
  const [userProfiles, setUserProfiles] = useState([]); // List of {username, connected: []}
  // Post-generation social nudge: shown at the results peak until the user
  // either connects a network or dismisses it. Only 2.7% of cloud users who
  // reach the social flow ever connect an account — this is the moment (clips
  // just appeared) with the best odds of moving that number.
  const [socialNudgeDismissed, setSocialNudgeDismissed] = useState(() => {
    try { return localStorage.getItem('os_social_nudge_dismissed') === '1'; } catch (_) { return false; }
  });
  const [showKeyModal, setShowKeyModal] = useState(false);
  const [jobId, setJobId] = useState(null);
  const [status, setStatus] = useState('idle'); // idle, processing, complete, error
  const [stopping, setStopping] = useState(false);
  const [logMode, setLogMode] = useState('key'); // 'key' = what matters, 'all' = raw pipeline output
  const handleStopWork = async () => {
    if (!jobId || !window.confirm('Stop this job now? Clips already finished are kept.')) return;
    setStopping(true);
    try {
      await apiFetch(`/api/jobs/${jobId}/cancel`, { method: 'POST' });
    } catch (e) {
      console.error('stop work failed', e);
    } finally {
      setTimeout(() => setStopping(false), 3000);
    }
  };
  const [results, setResults] = useState(null);
  // Gemini's own niche guess for this video (main.get_viral_clips,
  // gemini_worker.DetailClipModel.content_niche) — a suggestion, never forced:
  // only fills the Settings field when the user hasn't set one already, same
  // as it would if they'd typed it themselves, so it stays editable/correctable.
  useEffect(() => {
    if (results?.niche_guess && !niche.trim()) setNiche(results.niche_guess);
    // Deliberately keyed on the guess alone: `niche` is read as a guard, not
    // a trigger — including it would refire this on every keystroke in
    // Settings, which is exactly the "silently overwritten" bug this avoids.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [results?.niche_guess]);
  // Best clips first. The backend hands them back in transcript order, which
  // buries the strongest one wherever it happens to fall in the video — and
  // the first card is the one people actually watch and publish.
  //
  // The ORIGINAL array position travels with each clip and is what gets passed
  // down as `index`: it is the clip's identity everywhere else (clip_index on
  // /api/subtitle, /api/edit and publishing, the clip-N.mp4 download name, the
  // saved per-clip project state). Sorting the array itself would silently
  // repoint all of that at the wrong clip.
  const rankedClips = useMemo(() => {
    const clips = results?.clips;
    if (!Array.isArray(clips)) return [];
    return clips
      .map((clip, index) => ({ clip, index }))
      .sort((a, b) => {
        const sa = Number.isFinite(a.clip?.predicted_score) ? a.clip.predicted_score : -1;
        const sb = Number.isFinite(b.clip?.predicted_score) ? b.clip.predicted_score : -1;
        // Ties (and clips with no score at all) keep transcript order.
        return sb - sa || a.index - b.index;
      });
  }, [results]);
  // Posted clips leave the project (app.py _mark_clip_published) so nothing
  // gets posted twice; they stay reachable behind a "show posted" toggle,
  // with a one-click restore in case a platform rejected one.
  const [showPosted, setShowPosted] = useState(false);
  const postedCount = rankedClips.filter(({ clip }) => clip?.published).length;
  const visibleClips = rankedClips.filter(({ clip }) => showPosted || !clip?.published);
  // Bulk subtitles: apply one style to every clip of the job (triggered from
  // within a clip's subtitle modal via "apply to all").
  const [bulkSub, setBulkSub] = useState({ running: false, current: 0, total: 0, errors: 0 });
  const [downloadingAll, setDownloadingAll] = useState(false);
  // Pre-flight quality gate: { info: {max_height, min_height, cookies_invalid}, data }
  const [qualityGate, setQualityGate] = useState(null);
  const [logs, setLogs] = useState([]);
  // Collapsed on phones: the log tail is the least useful thing on a 360px
  // screen and it was pushing the actual clips a full scroll down.
  const [logsVisible, setLogsVisible] = useState(() => {
    try { return window.innerWidth >= 768; } catch { return true; }
  });
  const [processingMedia, setProcessingMedia] = useState(null);
  const [activeTab, setActiveTab] = useState('dashboard'); // dashboard, settings
  // Mobile only: the full nav lives in a drawer behind the header's menu button.
  const [navOpen, setNavOpen] = useState(false);
  // Reopened-project state (paid mode): per-clip {index, server_file, active_layers}
  // restored from the backend so ResultCards resume editing where they left off.
  const [projectState, setProjectState] = useState(null);
  // True when the current job was reopened from the library: its source video
  // was never persisted, so the session must not fall back to /api/source.
  const [noSource, setNoSource] = useState(false);

  const [sessionRecovered, setSessionRecovered] = useState(false);
  const [showScheduleWeek, setShowScheduleWeek] = useState(false);
  // Once a job is done and there's no source preview to show, the left panel
  // is only a status badge over a log nobody reads: fold it away and give the
  // clips the full width. The "logs" chip brings it back on demand.
  const [showJobPanel, setShowJobPanel] = useState(false);
  // The Synapse Cut profile picked in its tab (used by the results' "viral style").
  const [plusProfile, setPlusProfile] = useState(null);
  // Real progress from /api/status (app.py _job_progress): percent, stage,
  // clips done / total, ETA — computed from what the pipeline actually logs.
  const [jobProgress, setJobProgress] = useState(null);
  // Clip editor overlay: index of the clip being edited, or null.
  const [editingClip, setEditingClip] = useState(null);
  const [reframingClip, setReframingClip] = useState(null);

  // Silent-success "saved" states for the settings key inputs (design.md: no alert popups)
  const [elevenLabsSaved, setElevenLabsSaved] = useState(false);
  const [falSaved, setFalSaved] = useState(false);

  // Sync state for original video playback
  const [syncedTime, setSyncedTime] = useState(0);
  const [isSyncedPlaying, setIsSyncedPlaying] = useState(false);
  const [syncTrigger, setSyncTrigger] = useState(0);

  const handleClipPlay = (startTime) => {
    setSyncedTime(startTime);
    setIsSyncedPlaying(true);
    setSyncTrigger(prev => prev + 1);
  };

  const handleClipPause = () => {
    setIsSyncedPlaying(false);
  };

  // --- Project persistence (paid mode) ---
  // Debounced sync of each clip's browser-only edit state (Remotion layers +
  // current server file) to the backend, so a reopened project resumes intact.
  const clipStateSync = useRef({ jobId: null, pending: {}, files: {}, timer: null });
  // Read by in-flight async chases to notice that the user moved on to another job.
  const jobIdRef = useRef(jobId);
  useEffect(() => { jobIdRef.current = jobId; }, [jobId]);

  const flushClipState = () => {
    const s = clipStateSync.current;
    if (s.timer) { clearTimeout(s.timer); s.timer = null; }
    const entries = Object.entries(s.pending);
    if (!s.jobId || entries.length === 0) return;
    const clips = entries.map(([i, v]) => ({
      index: Number(i),
      active_layers: v.activeLayers,
      server_file: v.serverVideoFile,
    }));
    s.pending = {};
    apiFetch(`/api/projects/${s.jobId}/state`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ clips }),
    }).catch(() => {});
  };

  // One /api/history read, reduced to this job's clips.
  const fetchDurableMap = async () => {
    const d = await apiJson('/api/history');
    const map = {};
    for (const v of (d.videos || [])) {
      if (v.job_id === jobId && v.clip_index != null) map[v.clip_index] = { url: v.view_url, filename: v.filename };
    }
    return map;
  };

  // A server-side edit rewrites the clip's file while the R2 re-archive behind it
  // is still in flight (_archive_clip_edit_bg is fire-and-forget), so the durable
  // map goes stale and the card falls back to streaming from the API. Re-read the
  // map on a backoff until the archived name matches the clip's new file, then it
  // can play from R2 again. Gives up quietly: staying on /videos is correct, just
  // slower, and is exactly what happens for self-hosted users all the time.
  const chaseDurableFile = async (index, expectedFile) => {
    const forJob = jobId;
    for (const delay of [2500, 6000, 15000, 30000]) {
      await new Promise((r) => setTimeout(r, delay));
      if (jobIdRef.current !== forJob) return;
      let map;
      try { map = await fetchDurableMap(); } catch { return; }
      // A new job started mid-chase: this map describes the old one, so dropping
      // it here keeps it from overwriting the new job's URLs.
      if (jobIdRef.current !== forJob) return;
      setDurableClips(map);
      if (map[index]?.filename === expectedFile) return;
    }
  };

  const handleClipStateChange = (index, state) => {
    if (!isManaged || !jobId) return;
    const s = clipStateSync.current;
    if (s.jobId !== jobId) { s.pending = {}; s.files = {}; s.jobId = jobId; }
    s.pending[index] = state;
    // Cards report on mount too, so only an actual change of server file means an
    // edit just landed. The first report per clip is the mount, never a chase.
    const files = s.files || (s.files = {});
    const file = state?.serverVideoFile;
    if (file && files[index] !== file) {
      const isMount = files[index] === undefined;
      files[index] = file;
      if (!isMount) chaseDurableFile(index, file);
    }
    if (s.timer) clearTimeout(s.timer);
    s.timer = setTimeout(flushClipState, 2000);
  };

  // A recut replaced the clip's server file with a fresh render (burned layers
  // reset), so update the results, the reopened-project state and the synced
  // per-clip edit state, and let the ResultCard remount from the new file.
  const handleClipRerendered = (index, data) => {
    const newFile = (data.new_video_url || '').split('/').pop();
    setResults((prev) => {
      if (!prev?.clips?.[index]) return prev;
      const clips = prev.clips.slice();
      clips[index] = {
        ...clips[index],
        video_url: data.new_video_url,
        start: data.start,
        end: data.end,
        recipe: data.recipe,
      };
      return { ...prev, clips };
    });
    setProjectState((prev) => {
      if (!prev?.clips) return prev;
      return {
        ...prev,
        clips: prev.clips.map((c) => (c.index === index
          ? { ...c, server_file: newFile, active_layers: null }
          : c)),
      };
    });
    // The old durable R2 object is deleted when the recut is archived, so the
    // stale URL would 404 as a fallback; drop it until the next refresh.
    setDurableClips((prev) => {
      if (!(index in prev)) return prev;
      const next = { ...prev };
      delete next[index];
      return next;
    });
    handleClipStateChange(index, { activeLayers: null, serverVideoFile: newFile });
  };

  // Reopen an archived project from the History tab: the backend re-downloads
  // its files from R2 into the server's working dir and returns the full state.
  const restoreProject = async (projectJobId) => {
    // Self-host has no R2 archive to restore from — the job's files are
    // simply still on disk (JOB_RETENTION_SECONDS), and /api/status already
    // resolves any job id found there, in memory or not. Cloud goes through
    // the dedicated restore endpoint, which also pulls the job back from R2
    // if the local working files have since been swept.
    const data = billingEnabled
      ? await apiJson(`/api/projects/${projectJobId}/restore`, { method: 'POST' })
      : await apiJson(`/api/status/${projectJobId}`);
    flushClipState();
    setProjectState(data.project_state || null);
    setNoSource(true);
    setJobId(data.job_id || projectJobId);
    setResults(data.result || null);
    setLogs(['♻️ Project reopened.']);
    setProcessingMedia(null);
    setQualityGate(null);
    setStatus('complete');
    setActiveTab('dashboard');
  };

  // Apply one subtitle style to every clip of the job, sequentially.
  const handleBulkSubtitles = async (options) => {
    const clips = results?.clips || [];
    const total = clips.length;
    if (!total) return;
    setBulkSub({ running: true, current: 0, total, errors: 0 });
    let errors = 0;
    for (let i = 0; i < total; i++) {
      setBulkSub({ running: true, current: i + 1, total, errors });
      try {
        const res = await apiFetch('/api/subtitle', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            job_id: jobId,
            clip_index: i,
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
            // Chain from the clip's current server file (its video_url basename).
            input_filename: (clips[i].video_url || '').split('/').pop(),
          }),
        });
        if (!res.ok) errors++;
      } catch {
        errors++;
      }
    }
    setBulkSub({ running: false, current: total, total, errors });
    refreshMe();
    // Refresh results so each ResultCard picks up its new subtitled video_url.
    try {
      const data = await pollJob(jobId);
      if (data.result) setResults(data.result);
    } catch { /* keep current results */ }
  };

  // No niche saved yet -> ask first (in the same niche+history UI as
  // The niche belongs to the PROJECT: saved on it the first time it's
  // confirmed, then reused by every schedule/post/download of that project.
  // Proposed in order: this project's saved niche → the AI's guess for this
  // video → the last niche used anywhere.
  const projectNiche = results?.niche || '';
  const proposedNiche = projectNiche || results?.niche_guess || niche;
  // One account (Upload-Post profile) per niche: the project's own, else the
  // one Settings has selected.
  const projectProfile = results?.upload_profile || '';
  const postingProfile = projectProfile || uploadUserId;
  // The current project in the shape the shared scheduling form expects
  // (same as Publish Plan's /api/local-projects rows).
  const jobPanelFolded = status === 'complete' && !processingMedia && !showJobPanel;

  const scheduleProject = useMemo(() => (jobId && results?.clips ? {
    job_id: jobId,
    niche: results.niche || null,
    niche_guess: results.niche_guess || null,
    upload_profile: results.upload_profile || null,
    clips: results.clips.map((c, index) => ({
      index,
      title: c.video_title_for_youtube_short || `Clip ${index + 1}`,
      video_url: c.video_url,
      predicted_score: c.predicted_score,
      published: !!c.published,
    })),
  } : null), [jobId, results]);

  const saveProjectNiche = async (value, profile) => {
    const trimmed = (value || '').trim();
    if (trimmed) {
      setNiche(trimmed);
      setNicheHistory(pushNicheHistory(trimmed));
      if (profile) rememberNicheProfile(trimmed, profile);
    }
    setResults((prev) => (prev
      ? { ...prev, niche: trimmed || null, ...(profile ? { upload_profile: profile } : {}) }
      : prev));
    if (!jobId) return;
    try {
      await apiFetch(`/api/jobs/${jobId}/niche`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ niche: trimmed || null, ...(profile ? { profile } : {}) }),
      });
    } catch { /* kept locally for this session; next confirm retries */ }
  };

  // Re-read the job after anything that changes clips server-side (a post
  // marks its clip published) so the grid drops/restores cards immediately.
  const refreshResults = async () => {
    if (!jobId) return;
    try {
      const data = await pollJob(jobId);
      if (data.result) setResults(data.result);
    } catch { /* keep current results */ }
  };

  const restoreClip = async (index) => {
    try {
      await apiFetch(`/api/clip/${jobId}/${index}/restore`, { method: 'POST' });
    } finally {
      refreshResults();
    }
  };

  // Settings) instead of silently shipping a ZIP with no hashtags.
  const handleDownloadAll = () => {
    if (!jobId) return;
    setShowNichePrompt(true);
  };

  const downloadAllWithNiche = async (nicheForDownload) => {
    if (!jobId) return;
    setDownloadingAll(true);
    try {
      const trimmed = (nicheForDownload || '').trim();
      const qs = trimmed ? `?niche=${encodeURIComponent(trimmed)}` : '';
      const res = await apiFetch(`/api/jobs/${jobId}/download-all${qs}`);
      if (!res.ok) throw new Error(await res.text());
      if (trimmed) setNicheHistory(pushNicheHistory(trimmed));
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `openshorts_clips_${(jobId || '').slice(0, 8)}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      alert(`Download failed: ${e.message}`);
    } finally {
      setDownloadingAll(false);
    }
  };

  // Session Recovery: Restore on mount
  useEffect(() => {
    try {
      const saved = localStorage.getItem(SESSION_KEY);
      if (!saved) return;
      const session = JSON.parse(saved);
      if (Date.now() - session.timestamp > SESSION_MAX_AGE) {
        localStorage.removeItem(SESSION_KEY);
        return;
      }
      if (session.jobId && session.status && session.status !== 'idle') {
        setJobId(session.jobId);
        setResults(session.results || null);
        // Restore the source preview. Older sessions (or uploads) saved no
        // media, so fall back to the backend-served source for this job —
        // except for reopened projects, whose source was never persisted.
        if (session.processingMedia) setProcessingMedia(session.processingMedia);
        else if (!session.noSource) setProcessingMedia({ type: 'server', payload: `/api/source/${session.jobId}` });
        if (session.noSource) setNoSource(true);
        if (session.projectState) setProjectState(session.projectState);
        if (session.activeTab) setActiveTab(session.activeTab);
        // If was processing, resume polling; if complete/error, just show results
        setStatus(session.status === 'processing' ? 'processing' : session.status);
        // The saved snapshot can be stale (a clip posted/scheduled since, which
        // takes it out of the project): show it instantly, then swap in the
        // server's current state so a posted clip can't reappear on reload.
        if (session.status === 'complete') {
          pollJob(session.jobId)
            .then((d) => { if (d?.result?.clips) setResults(d.result); })
            .catch(() => { /* keep the snapshot */ });
        }
        setSessionRecovered(true);
        setTimeout(() => setSessionRecovered(false), 5000);
      }
    } catch (e) {
      localStorage.removeItem(SESSION_KEY);
    }
  }, []);

  // Session Recovery: Save state changes
  useEffect(() => {
    if (status === 'idle') {
      localStorage.removeItem(SESSION_KEY);
      return;
    }
    try {
      // URL (YouTube) media serializes as-is. Uploaded 'file' media is a blob
      // that can't be persisted, so point the recovered preview at the source
      // served by the backend instead of dropping it.
      let persistMedia = null;
      if (processingMedia?.type === 'url') persistMedia = processingMedia;
      else if (processingMedia && jobId) persistMedia = { type: 'server', payload: `/api/source/${jobId}` };
      const sessionData = {
        jobId,
        status,
        results,
        processingMedia: persistMedia,
        activeTab,
        noSource,
        projectState,
        timestamp: Date.now()
      };
      localStorage.setItem(SESSION_KEY, JSON.stringify(sessionData));
    } catch (e) {
      // localStorage full or serialization error - ignore
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, status, results, activeTab, noSource, projectState]);

  useEffect(() => {
    // Encrypt Gemini Key too for consistency if desired, but user asked specifically about Social integration not saving well.
    // For now keeping gemini plain for compatibility unless requested.
    if (apiKey) localStorage.setItem('gemini_key', apiKey);
  }, [apiKey]);

  useEffect(() => {
    if (uploadPostKey) {
      localStorage.setItem('uploadPostKey_v3', encrypt(uploadPostKey));
    }
    if (uploadUserId) {
      localStorage.setItem('uploadUserId', uploadUserId);
    }
  }, [uploadPostKey, uploadUserId]);

  useEffect(() => {
    if (elevenLabsKey) {
      localStorage.setItem('elevenLabsKey_v1', encrypt(elevenLabsKey));
    }
  }, [elevenLabsKey]);

  useEffect(() => {
    if (falKey) {
      localStorage.setItem('falKey_v1', encrypt(falKey));
    }
  }, [falKey]);

  useEffect(() => {
    if ((uploadPostKey || isManaged) && userProfiles.length === 0) {
      fetchUserProfiles({ silent: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uploadPostKey, isManaged]);

  // For managed users, fetch the durable R2 URLs of the current job's clips. The
  // preview player prefers them (free egress, edge-served, and not competing with
  // the renders for the API process), and falls back to /videos when the local
  // file is newer than the archived one or the signed link fails.
  // Kept fresh by chaseDurableFile after each edit and by the completion chase
  // below; until either lands, the card just streams from /videos.
  useEffect(() => {
    if (!isManaged || !jobId || !(results?.clips?.length)) { setDurableClips({}); return; }
    let cancelled = false;
    fetchDurableMap()
      .then((map) => { if (!cancelled) setDurableClips(map); })
      .catch(() => {});
    return () => { cancelled = true; };
    // Keyed on the clip COUNT, not on results: the status poll hands back a new
    // results object every couple of seconds while the job runs, and this used to
    // re-read the history on every one of them.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isManaged, jobId, results?.clips?.length]);

  // A job is marked complete BEFORE _archive_managed_job has finished uploading
  // (app.py:878), so the read above can land while R2 still has nothing for it and
  // every card would stream from the API for the rest of the session. Chase until
  // all clips have a durable copy.
  useEffect(() => {
    const count = results?.clips?.length || 0;
    if (!isManaged || !jobId || status !== 'complete' || !count) return;
    let cancelled = false;
    (async () => {
      for (const delay of [0, 3000, 8000, 20000, 40000]) {
        if (delay) await new Promise((r) => setTimeout(r, delay));
        if (cancelled) return;
        let map;
        try { map = await fetchDurableMap(); } catch { return; }
        if (cancelled) return;
        setDurableClips(map);
        if (Object.keys(map).length >= count) return;
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isManaged, jobId, status, results?.clips?.length]);

  useEffect(() => {
    let interval;
    if ((status === 'processing' || status === 'completed') && jobId) {
      interval = setInterval(async () => {
        try {
          const data = await pollJob(jobId);
          console.log("Job status:", data);

          if (data.progress) setJobProgress(data.progress);
          // Update results if available (real-time)
          if (data.result) {
            setResults(data.result);
          }

          if (data.status === 'completed') {
            setStatus('complete');
            clearInterval(interval);
            refreshMe();
          } else if (data.status === 'failed') {
            setStatus('error');
            const errorMsg = data.error || (data.logs && data.logs.length > 0 ? data.logs[data.logs.length - 1] : "Process failed");
            setLogs(prev => [...prev, "Error: " + errorMsg]);
            clearInterval(interval);
            refreshMe();
          } else {
            // Update logs if available
            if (data.logs) setLogs(data.logs);
          }
        } catch (e) {
          console.error("Polling error", e);
        }
      }, 2000);
    }
    return () => clearInterval(interval);
  }, [status, jobId, refreshMe]);


  // silent: background auto-fetch — never alert(), just log. Managed users need
  // no local key (the server resolves its own); BYOK sends the header.
  // The Settings "connect" button used to succeed silently — it only ever spoke
  // up on failure, so a working key looked like a dead button. Now it always
  // says what happened. (onClick passes the click event: not an options bag.)
  const [connectStatus, setConnectStatus] = useState(null); // null | 'loading' | { ok, msg }
  const fetchUserProfiles = async (opts) => {
    const silent = !!(opts && opts.silent === true);
    if (!uploadPostKey && !isManaged) {
      if (!silent) setConnectStatus({ ok: false, msg: 'Paste your Upload-Post API key first.' });
      return;
    }
    if (!silent) setConnectStatus('loading');
    try {
      const res = await apiFetch('/api/social/user', {
        headers: uploadPostKey ? { 'X-Upload-Post-Key': uploadPostKey } : {}
      });
      if (!res.ok) throw new Error("Failed to fetch");
      const data = await res.json();
      if (data.profiles && data.profiles.length > 0) {
        setUserProfiles(data.profiles);
        // Auto select first if none selected
        if (!uploadUserId) {
          setUploadUserId(data.profiles[0].username);
        }
        if (!silent) setConnectStatus({ ok: true, msg: `Connected · ${data.profiles.length} profile${data.profiles.length === 1 ? '' : 's'} found` });
      } else if (!silent) {
        setConnectStatus({ ok: false, msg: 'Key accepted, but no profiles yet — create one at upload-post.com (step 2).' });
      }
    } catch (e) {
      if (!silent) setConnectStatus({ ok: false, msg: 'Upload-Post refused this key — check it was copied in full.' });
      console.error(e);
    }
  };

  // Hosted is paid-only (no BYOK core). Self-host uses BYOK keys.
  // `keysMissing` now means "self-host BYOK keys missing" — it never fires on hosted.
  // A self-hosted server running the moment picker on a local LLM
  // (LLM_BASE_URL) does not need a Gemini key for the core pipeline.
  const geminiOk = !!apiKey || !!localLlm;
  const keysMissing = !billingEnabled && (!geminiOk || !uploadPostKey);
  const needsPlan = billingEnabled && !isManaged;   // hosted, signed-out or no active plan/trial

  // Fresh sign-up: Clip Generator tutorial (AuthContext set os_show_clip_tutorial
  // after the auth redirect). QA: #app?tutorial=1. Resume coach if they refreshed
  // mid-job. Runs once on mount so a later isSignedIn flip cannot reset intro→coach.
  useEffect(() => {
    let showTutorial = false;
    let resumeCoach = false;
    try {
      const q = new URLSearchParams((window.location.hash.split('?')[1] || ''));
      const qa = q.get('tutorial');
      if (qa === '1') showTutorial = true;
      if (qa === 'coach') resumeCoach = true;
      if (qa === 'celebrate') { setTutorialPhase('celebrate'); return; }
      if (localStorage.getItem('os_show_clip_tutorial') === '1') showTutorial = true;
      if (localStorage.getItem('os_clip_tutorial') === 'coach') resumeCoach = true;
    } catch (_) { /* ignore */ }
    if (showTutorial) {
      setTutorialPhase('intro');
      setActiveTab('dashboard');
    } else if (resumeCoach) {
      setTutorialPhase('coach');
      setActiveTab('dashboard');
    }
  }, []);

  // Legacy: an older build may still have set os_show_plan_choice. Don't open it
  // on top of the tutorial.
  useEffect(() => {
    if (tutorialPhase) return;
    if (!(billingEnabled && isSignedIn)) return;
    let showPlans = false;
    try { showPlans = localStorage.getItem('os_show_plan_choice') === '1'; } catch (_) { /* ignore */ }
    if (showPlans) {
      setShowPlanChoice(true);
      try { localStorage.removeItem('os_show_plan_choice'); } catch (_) { /* ignore */ }
    }
  }, [billingEnabled, isSignedIn, tutorialPhase]);

  const tutorialLock = tutorialPhase === 'intro' || tutorialPhase === 'coach' || tutorialPhase === 'celebrate';

  // Self-host opt-in (dashboard/.env.local: VITE_HIDE_CLASSIC_CLIPGEN=1): only
  // Synapse Cut (ex Clip Generator++) is shown. The classic tab's code stays; every path that
  // lands on it (reopened project, "back" from another tool) goes to ++ instead.
  const hideClassic = !billingEnabled && import.meta.env.VITE_HIDE_CLASSIC_CLIPGEN === '1';

  useEffect(() => {
    if (tutorialLock && activeTab !== 'dashboard') setActiveTab('dashboard');
    else if (hideClassic && !tutorialLock && activeTab === 'dashboard') setActiveTab('plus');
  }, [tutorialLock, activeTab, hideClassic]);

  useEffect(() => {
    if (tutorialPhase === 'coach' && status === 'complete' && (results?.clips?.length > 0)) {
      setTutorialPhase('celebrate');
      track('ClipTutorialCompleted', { props: { clips: results.clips.length } });
    }
  }, [tutorialPhase, status, results]);

  const finishTutorial = () => {
    try { localStorage.setItem('os_clip_tutorial', 'done'); } catch (_) { /* ignore */ }
    try { localStorage.removeItem('os_show_clip_tutorial'); } catch (_) { /* ignore */ }
    setTutorialPhase(null);
  };
  const startTutorial = () => {
    try { localStorage.setItem('os_clip_tutorial', 'coach'); } catch (_) { /* ignore */ }
    try { localStorage.removeItem('os_show_clip_tutorial'); } catch (_) { /* ignore */ }
    track('ClipTutorialStarted');
    setTutorialPhase('coach');
    setActiveTab('dashboard');
  };
  const skipTutorial = () => {
    track('ClipTutorialSkipped', { props: { phase: tutorialPhase } });
    finishTutorial();
  };
  // Included in the plan (fully managed, no keys): Clip Generator + YouTube Studio.
  // Advanced (bring your own fal.ai + ElevenLabs keys): AI Shorts.
  const INCLUDED_TOOL_TABS = ['dashboard', 'thumbnails'];
  const ADVANCED_TOOL_TABS = ['saasshorts'];
  const TOOL_NAMES = { dashboard: 'the Clip generator', thumbnails: 'YouTube Studio' };
  const gateThisTab = needsPlan && INCLUDED_TOOL_TABS.includes(activeTab);      // included tool, no plan yet
  const advancedThisTab = billingEnabled && ADVANCED_TOOL_TABS.includes(activeTab); // BYOK-notice tools

  // Social nudge visibility: managed users with clips on screen and no network
  // connected yet. userProfiles being empty (not yet fetched / none created)
  // also counts as "not connected" — that is the 97% case.
  const connectedSocials = ((userProfiles.find((p) => p.username === uploadUserId) || userProfiles[0])?.connected) || [];
  const showSocialNudge = isManaged && !socialNudgeDismissed && connectedSocials.length === 0 && !tutorialLock;

  // One Seen event per job, only when the banner actually rendered.
  const socialNudgeSeenRef = useRef(null);
  useEffect(() => {
    if (status === 'complete' && (results?.clips?.length > 0) && showSocialNudge && socialNudgeSeenRef.current !== jobId) {
      socialNudgeSeenRef.current = jobId;
      track('SocialNudgeSeen', { props: { clips: results.clips.length } });
    }
  }, [status, results, showSocialNudge, jobId]);

  // Managed users connect their socials via Upload-Post's branded hosted page.
  const handleConnectSocials = async () => {
    try {
      const { access_url } = await apiJson('/api/social/connect', { method: 'POST' });
      // Same tab so the connect page's redirectUrl brings the user back into the app.
      if (access_url) window.location.href = access_url;
    } catch (e) {
      alert('Could not open the connection page. Please try again.');
    }
  };

  // Open the Upload-Post white-label page (which includes the scheduling calendar)
  // in a new tab, for consulting/managing scheduled posts from the dashboard.
  const handleOpenCalendar = async () => {
    try {
      const { access_url } = await apiJson('/api/social/connect', { method: 'POST' });
      if (access_url) window.open(access_url, '_blank', 'noopener');
    } catch (e) {
      alert('Could not open the calendar. Please try again.');
    }
  };

  const handleProcess = async (data, forceLowQuality = false) => {
    // Hosted: must be signed in AND on an active plan/trial. Self-host: BYOK keys.
    if (billingEnabled) {
      if (!isSignedIn) { setShowLogin(true); return; }
      if (!isManaged) { window.location.hash = '#/pricing'; return; }
    } else if (keysMissing) {
      setShowKeyModal(true);
      return;
    }
    setStatus('processing');
    setJobProgress(null);
    setLogs(["Starting process..."]);
    setResults(null);
    // Studio handovers have no local media object; the preview switches to the
    // backend-served source once the job id is known.
    setProcessingMedia(data.type === 'thumbnail_session' ? null : data);
    setQualityGate(null);
    setProjectState(null);
    setNoSource(false);

    try {
      let body;
      // BYOK sends the Gemini header; managed users rely on the bearer token
      // that apiFetch attaches automatically.
      const headers = apiKey ? { 'X-Gemini-Key': apiKey } : {};
      // "Publish the 3 best clips": the server schedules them on Upload-Post
      // when the job ends, so it needs the key now (kept in memory only).
      if (data.autoPublish && uploadPostKey) headers['X-Upload-Post-Key'] = uploadPostKey;
      const autoNiche = (data.autoPublish?.niche || '').trim();
      if (autoNiche) {
        setNicheHistory(pushNicheHistory(autoNiche));
        if (data.autoPublish.profile) rememberNicheProfile(autoNiche, data.autoPublish.profile);
      }

      // Advanced generation controls: only sent when the user set them, so the
      // default request stays byte-identical to the pre-feature one.
      const advanced = {
        target_clips: data.targetClips || null,
        clip_min_seconds: data.clipMinSeconds || null,
        clip_max_seconds: data.clipMaxSeconds || null,
        // Sent explicitly both ways: absent means off for raw API callers,
        // but the dashboard always states the user's choice.
        auto_hook: data.autoHook ? '1' : '0',
        auto_hook_style: data.autoHook ? (data.autoHookStyle || 'classic') : null,
        // 'auto' is the server default, so only a deliberate choice travels.
        layouts: data.layout && data.layout !== 'auto' ? data.layout : null,
        // Whatever the user last marked "default" in the subtitle editor's
        // "My Profiles" — otherwise the automatic caption pass every new
        // clip gets always used subtitles.AUTO_CAPTION_STYLE regardless of
        // what they configured there (SubtitleModal.jsx only ever applied
        // it when the editor was reopened by hand).
        plus_profile_id: data.plusProfileId || null,
        auto_publish: data.autoPublish ? JSON.stringify({
          count: 3,
          platforms: data.autoPublish.platforms,
          profile: data.autoPublish.profile || null,
          default_profile: uploadUserId || null,
          niche: autoNiche || null,
          timezone: userTimezone(),
        }) : null,
        caption_style: (() => {
          const s = activeSubtitleProfileSettings(loadSubtitleProfileStore());
          return JSON.stringify({
            position_percent: s.position, font_name: s.fontName, font_color: s.fontColor,
            highlight_color: s.highlightColor, border_color: s.borderColor, border_width: s.borderWidth,
            effect: s.effect, base_opacity: s.baseOpacity, uppercase: s.uppercase,
            font_size: s.fontSize, letter_spacing: s.letterSpacing, max_words: s.maxWords,
          });
        })(),
      };

      if (data.type === 'url') {
        headers['Content-Type'] = 'application/json';
        body = JSON.stringify({
          url: data.payload,
          acknowledged: !!data.acknowledged,
          output_format: data.outputFormat || 'auto',
          force_low_quality: forceLowQuality,
          ...Object.fromEntries(Object.entries(advanced).filter(([, v]) => v != null)),
        });
      } else if (data.type === 'thumbnail_session') {
        // Handover from Thumbnail Studio (issue #68): the video and transcript
        // already live server-side, keyed by the Studio session.
        headers['Content-Type'] = 'application/json';
        body = JSON.stringify({
          thumbnail_session_id: data.payload,
          acknowledged: !!data.acknowledged,
          output_format: data.outputFormat || 'auto',
          ...Object.fromEntries(Object.entries(advanced).filter(([, v]) => v != null)),
        });
      } else {
        const formData = new FormData();
        formData.append('file', data.payload);
        formData.append('acknowledged', data.acknowledged ? 'true' : 'false');
        formData.append('output_format', data.outputFormat || 'auto');
        for (const [k, v] of Object.entries(advanced)) {
          if (v != null) formData.append(k, v);
        }
        body = formData;
      }

      const res = await apiFetch('/api/process', { method: 'POST', headers, body });

      if (!res.ok) throw new Error(await res.text());
      const resData = await res.json();

      // Quality gate: the source is below the min resolution — ask before burning
      // 20 min on it. On confirm we resend with force_low_quality.
      if (resData.needs_confirmation) {
        setStatus('idle');
        setQualityGate({ info: resData.quality_check, data });
        return;
      }

      setJobId(resData.job_id);
      if (data.type === 'thumbnail_session') {
        setProcessingMedia({ type: 'server', payload: `/api/source/${resData.job_id}` });
      }
      // Minutes are reserved at job start, not at complete.
      refreshMe();

    } catch (e) {
      if (e instanceof QuotaError) {
        setStatus('idle');
        refreshMe();
        // Trial users hit the trial minute cap → prompt them to activate the plan
        // now (unlocks full minutes). Active users → offer a top-up.
        if (me?.status === 'trialing') {
          setShowTrialUpgrade(true);
        } else {
          setTopUpInfo({ required: e.minutesRequired, remaining: e.minutesRemaining });
          setShowTopUp(true);
        }
        return;
      }
      setStatus('error');
      setLogs(l => [...l, `Error starting job: ${e.message}`]);
    }
  };

  const handleReset = () => {
    // Flush any pending edit-state sync before dropping the project: the clips
    // themselves are already archived to R2 as they were edited.
    flushClipState();
    setStatus('idle');
    setJobId(null);
    setResults(null);
    setLogs([]);
    setProcessingMedia(null);
    setProjectState(null);
    setNoSource(false);
    localStorage.removeItem(SESSION_KEY);
  };

  // --- UI Components ---

  // Synapse AI shell (4-oct-2026): one nav definition, grouped by what you do — create, library, grow — drives the
  // desktop rail, the mobile drawer and the bottom tab bar. `short` is the tab-bar label, `desc` the line under the
  // page title in the top bar (and the rail's tooltip).
  const navItems = [
    ...(hideClassic ? [] : [{ id: 'dashboard', group: 'create', icon: LayoutDashboard, label: 'Clip generator', short: 'Clips', primary: true,
      desc: 'Paste a link or drop a video: the best moments, cut into vertical shorts.' }]),
    ...(!billingEnabled ? [{ id: 'plus', group: 'create', icon: Rocket, label: 'Synapse Cut', short: 'Cut', primary: hideClassic,
      desc: 'Your channel profiles: moments, hooks, captions and drawn B-roll, in your house style.' }] : []),
    { id: 'saasshorts', group: 'create', icon: Sparkles, label: 'AI Shorts', short: 'AI Shorts', byok: true, primary: true,
      desc: 'Generate a short from a script or a product, voiced and edited by AI.' },
    ...(!billingEnabled ? [{ id: 'story', group: 'create', icon: Clapperboard, label: 'Story channel', short: 'Story',
      desc: 'Long stories told as a series of shorts.' }] : []),
    ...(!billingEnabled || isSignedIn ? [{ id: 'history', group: 'library', icon: History, label: 'History', short: 'History',
      desc: 'Every project you made, ready to reopen.' }] : []),
    { id: 'ugc-gallery', group: 'library', icon: LayoutGrid, label: 'UGC gallery', short: 'Gallery', primary: true,
      desc: 'The videos generated with AI actors.' },
    ...(!billingEnabled ? [{ id: 'broll-gallery', group: 'library', icon: Images, label: 'B-roll images', short: 'Images',
      desc: 'Every drawn picture, kept or refused: thumbs up or down, why, what to change.' }] : []),
    ...(!billingEnabled ? [{ id: 'notions', group: 'library', icon: Library, label: 'Notion pictures', short: 'Notions',
      desc: 'The pictures kept for the notions of your episodes.' }] : []),
    { id: 'thumbnails', group: 'grow', icon: Image, label: 'YouTube Studio', short: 'Studio', primary: true,
      desc: 'Thumbnails, titles and descriptions for YouTube.' },
    ...(!billingEnabled ? [{ id: 'viral-finder', group: 'grow', icon: Flame, label: 'Viral finder', short: 'Finder',
      desc: 'Find the videos that are taking off in your niche.' }] : []),
    { id: 'reworker', group: 'grow', icon: Eraser, label: 'Viral clip reworker', short: 'Reworker', byok: true,
      desc: 'Take a viral clip and make it yours.' },
    ...(!billingEnabled ? [{ id: 'publish-plan', group: 'grow', icon: Calendar, label: 'Publish plan', short: 'Plan',
      desc: 'Plan and schedule your posts across platforms.' }] : []),
    { id: 'settings', group: 'system', icon: Settings, label: 'Settings', short: 'Settings',
      desc: 'Your niche, API keys and connected accounts.' },
  ];
  const NAV_GROUPS = [
    { id: 'create', label: 'Create' },
    { id: 'library', label: 'Library' },
    { id: 'grow', label: 'Grow' },
  ];
  const activeNav = navItems.find((n) => n.id === activeTab);
  const activeGroup = NAV_GROUPS.find((g) => g.id === activeNav?.group);
  const newClipTab = hideClassic ? 'plus' : 'dashboard';

  // Escape closes the mobile drawer. The shell itself is overflow-hidden, so
  // there is no body scroll to lock behind it.
  useEffect(() => {
    if (!navOpen) return;
    const onKey = (e) => { if (e.key === 'Escape') setNavOpen(false); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [navOpen]);

  const goToTab = (id) => {
    if (tutorialLock && id !== 'dashboard') return;
    setActiveTab(id);
    setNavOpen(false);
  };
  const tabLocked = (id) => tutorialLock && id !== 'dashboard';

  // One nav button, the same in the rail (``compact`` from md to lg: icon only) and the drawer.
  // Monochrome at rest; the active page is the raised tile with the signal on its edge.
  const NavButton = ({ item, compact = false, drawer = false }) => {
    const NavIcon = item.icon;
    const isActive = activeTab === item.id;
    const locked = tabLocked(item.id);
    return (
      <button
        type="button"
        data-tutorial={item.id === 'dashboard' ? 'nav-clips' : undefined}
        onClick={() => goToTab(item.id)}
        disabled={locked}
        aria-current={isActive ? 'page' : undefined}
        aria-label={compact ? `${item.label}${locked ? ' (locked)' : ''}` : undefined}
        title={locked ? 'Finish your first clips to unlock' : `${item.label}: ${item.desc}`}
        className={`group relative w-full flex items-center gap-3 rounded-input transition-colors py-2 ${drawer ? 'min-h-[44px]' : 'min-h-[44px] md:min-h-[40px]'}
          ${compact ? 'justify-center lg:justify-start px-0 lg:px-3' : 'px-3'}
          ${isActive ? 'nav-tile-active' : 'text-ink2 hover:text-ink hover:bg-paper3'}
          ${locked ? 'opacity-40 cursor-not-allowed hover:bg-transparent hover:text-ink2' : ''}`}
      >
        <NavIcon size={17} className={`shrink-0 transition-colors ${isActive ? 'text-ink' : 'text-muted group-hover:text-ink2'}`} aria-hidden="true" />
        <span className={`text-sm flex-1 text-left truncate ${isActive ? 'font-medium' : ''} ${compact ? 'hidden lg:block' : ''}`}>{item.label}</span>
        {locked ? (
          <span className={`shrink-0 text-muted ${compact ? 'hidden lg:inline-flex' : 'inline-flex'}`}>
            <Lock size={12} aria-hidden="true" />
            {!compact && <span className="sr-only">(locked)</span>}
          </span>
        ) : item.byok ? (
          <span className={`chip-byok ${compact ? 'hidden lg:inline-flex' : ''}`} title="Bring your own keys (fal.ai, ElevenLabs)">BYOK</span>
        ) : null}
      </button>
    );
  };

  // The rail's and the drawer's sections: Create, Library, Grow — a mono label
  // and a hairline filament, then the tools. Settings is pinned below.
  const NavSections = ({ compact = false, drawer = false }) => (
    <>
      {NAV_GROUPS.map((g) => {
        const items = navItems.filter((n) => n.group === g.id);
        if (!items.length) return null;
        const labelId = `nav-group-${g.id}${drawer ? '-d' : ''}`;
        return (
          <div key={g.id} className="space-y-0.5" role="group" aria-labelledby={labelId}>
            <p id={labelId}
              className={`nav-group-label items-center gap-2.5 px-3 pt-5 pb-2 ${compact ? 'sr-only lg:not-sr-only lg:flex' : 'flex'}`}>
              <span>{g.label}</span>
              <span className="flex-1 border-t border-rule" aria-hidden="true" />
            </p>
            {compact && <div className="lg:hidden mx-3 my-3 border-t border-rule" aria-hidden="true" />}
            {items.map((item) => <NavButton key={item.id} item={item} compact={compact} drawer={drawer} />)}
          </div>
        );
      })}
    </>
  );

  // Shared footer links — same list in the desktop rail and the mobile drawer, so they can never drift apart.
  // Collapsed rail (md to lg): icon only, centred.
  const footerLink = 'flex items-center gap-2.5 py-2 min-h-[44px] md:min-h-[34px] text-xs text-muted hover:text-ink transition-colors rounded-input';
  const NavFooterLinks = ({ collapsed = false }) => (
    <>
      <a href="#landing" aria-label={collapsed ? 'Synapse AI home' : undefined}
        className={`${footerLink} ${collapsed ? 'justify-center lg:justify-start px-0 lg:px-3' : 'px-3'}`}>
        <Globe size={14} className="shrink-0" aria-hidden="true" />
        <span className={collapsed ? 'hidden lg:block truncate' : 'truncate'}>Synapse AI home</span>
      </a>
      <a
        href="https://github.com/mutonby/openshorts"
        target="_blank"
        rel="noopener noreferrer"
        aria-label={collapsed ? 'Built on OpenShorts (MIT), opens GitHub in a new tab' : undefined}
        className={`${footerLink} ${collapsed ? 'justify-center lg:justify-start px-0 lg:px-3' : 'px-3'}`}
        title="Synapse AI is built on OpenShorts, open source under the MIT license"
      >
        <svg height="14" viewBox="0 0 16 16" version="1.1" width="14" aria-hidden="true" fill="currentColor" className="shrink-0"><path fillRule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"></path></svg>
        <span className={collapsed ? 'hidden lg:block truncate' : 'truncate'}>Built on OpenShorts (MIT)</span>
      </a>
      {billingEnabled && (
        <a href="#/pricing" aria-label={collapsed ? 'Plans and pricing' : undefined}
          className={`${footerLink} ${collapsed ? 'justify-center lg:justify-start px-0 lg:px-3' : 'px-3'}`}>
          <Sparkles size={14} className="shrink-0" aria-hidden="true" />
          <span className={collapsed ? 'hidden lg:block truncate' : 'truncate'}>Plans and pricing</span>
        </a>
      )}
    </>
  );

  // The brand block, the same in the rail and the drawer: the neuron mark and
  // the wordmark, "AI" in the signal.
  const Brand = ({ compact = false, onClick }) => (
    <a href="#landing" onClick={onClick} aria-label="Synapse AI home" title="Synapse AI home"
      className="flex items-center gap-2.5 min-w-0 rounded-input">
      <img src="/logo-synapse.svg" alt="" className="w-9 h-9 shrink-0 rounded-input" />
      <span className={`flex flex-col leading-none ${compact ? 'hidden lg:flex' : ''}`}>
        <span className="brand-word text-[1.12rem]">Synapse <span className="brand-ai">AI</span></span>
        <span className="readout mt-1.5">Clip studio</span>
      </span>
    </a>
  );

  const NewClipButton = ({ compact = false }) => (
    <button
      type="button"
      onClick={() => goToTab(newClipTab)}
      className={`btn-accent w-full ${compact ? 'px-0 lg:px-4' : 'px-4'} py-2.5 text-sm`}
      aria-label="New clip"
    >
      <Plus size={16} aria-hidden="true" />
      <span className={compact ? 'hidden lg:inline' : ''}>New clip</span>
    </button>
  );

  // Desktop rail: icon-only from md, labelled from lg. Below md it is gone — a phone gets the drawer and the tab bar.
  // One nav landmark holds every destination: the groups scroll, Settings stays pinned at the foot.
  const Sidebar = () => (
    <aside className="hidden md:flex w-[76px] lg:w-[264px] shell-rail flex-col h-full shrink-0" aria-label="Studio">
      <div className="px-3 lg:px-5 pt-5 pb-5 flex items-center justify-center lg:justify-start">
        <Brand compact />
      </div>
      <div className="px-3 lg:px-4">
        <NewClipButton compact />
      </div>
      <nav className="flex-1 min-h-0 flex flex-col mt-2" aria-label="Main">
        <div className="flex-1 overflow-y-auto custom-scrollbar px-2.5 lg:px-3 pb-3">
          <NavSections compact />
        </div>
        <div className="px-2.5 lg:px-3 pt-2 border-t border-rule">
          {navItems.filter((n) => n.group === 'system').map((item) => <NavButton key={item.id} item={item} compact />)}
        </div>
      </nav>
      <div className="px-2.5 lg:px-3 pt-1 pb-3">
        <NavFooterLinks collapsed />
      </div>
    </aside>
  );

  // Mobile drawer: the complete nav, reachable from the top bar's menu button and the tab bar's "More".
  const MobileNavDrawer = () => (
    <div className="md:hidden fixed inset-0 z-[90] flex" role="dialog" aria-modal="true" aria-label="Navigation">
      <div className="absolute inset-0 bg-paper/80 animate-fade" onClick={() => setNavOpen(false)} aria-hidden="true" />
      <div className="relative w-[18rem] max-w-[86vw] h-full shell-rail bg-paper2 flex flex-col animate-slide-in-left">
        <div className="flex items-center justify-between gap-3 pl-4 pr-2 h-16 border-b border-rule shrink-0">
          <Brand onClick={() => setNavOpen(false)} />
          <button type="button" onClick={() => setNavOpen(false)} aria-label="Close navigation"
            className="w-11 h-11 flex items-center justify-center rounded-input text-muted hover:text-ink hover:bg-paper3 transition-colors">
            <X size={20} aria-hidden="true" />
          </button>
        </div>
        <div className="px-4 pt-4"><NewClipButton /></div>
        <nav className="flex-1 overflow-y-auto custom-scrollbar px-3 pb-3" aria-label="Main">
          <NavSections drawer />
          <div className="pt-3 mt-3 border-t border-rule">
            {navItems.filter((n) => n.group === 'system').map((item) => <NavButton key={item.id} item={item} drawer />)}
          </div>
        </nav>
        <div className="px-3 py-2 border-t border-rule safe-bottom shrink-0">
          <NavFooterLinks />
        </div>
      </div>
    </div>
  );

  // Bottom tab bar: the everyday destinations plus "More" for the rest. A flex sibling of the scrolling pane rather
  // than `fixed`, so nothing ever hides behind it and no pane needs compensating padding. The active tab carries the
  // signal as a short filament along its top edge.
  const MobileTabBar = () => {
    const tabs = navItems.filter((n) => n.primary);
    const moreActive = !tabs.some((t) => t.id === activeTab);
    const tabClass = (active) => `relative flex-1 min-w-0 flex flex-col items-center justify-center gap-1.5 py-2 min-h-[56px] transition-colors
      ${active ? 'text-ink' : 'text-muted active:text-ink2'}`;
    const ActiveEdge = () => <span className="absolute top-0 inset-x-3 h-0.5 rounded-b bg-vermilion" aria-hidden="true" />;
    return (
      <nav className="md:hidden shrink-0 border-t border-rule bg-paper2 safe-bottom" aria-label="Quick sections">
        <div className="flex items-stretch">
          {tabs.map((item) => {
            const NavIcon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                type="button"
                data-tutorial={item.id === 'dashboard' ? 'nav-clips' : undefined}
                onClick={() => goToTab(item.id)}
                disabled={tabLocked(item.id)}
                aria-current={isActive ? 'page' : undefined}
                title={tabLocked(item.id) ? 'Finish your first clips to unlock' : item.label}
                className={`${tabClass(isActive)} ${tabLocked(item.id) ? 'opacity-40 cursor-not-allowed' : ''}`}
              >
                {isActive && <ActiveEdge />}
                <NavIcon size={19} aria-hidden="true" />
                <span className={`text-[11px] leading-none truncate max-w-full px-0.5 ${isActive ? 'font-medium' : ''}`}>{item.short}</span>
              </button>
            );
          })}
          <button
            type="button"
            onClick={() => setNavOpen(true)}
            aria-label="More sections"
            aria-expanded={navOpen}
            className={tabClass(moreActive)}
          >
            {moreActive && <ActiveEdge />}
            <Menu size={19} aria-hidden="true" />
            <span className={`text-[11px] leading-none ${moreActive ? 'font-medium' : ''}`}>More</span>
          </button>
        </div>
      </nav>
    );
  };

  return (
    /* h-dvh where supported: on mobile Safari/Chrome `100vh` is the tallest the
       viewport ever gets, so a h-screen shell hides its own bottom bar behind
       the browser chrome until the user scrolls. */
    <div className="flex h-screen supports-[height:100dvh]:h-[100dvh] overflow-hidden synapse-shell">
      <a href="#main-content" className="skip-link">Skip to content</a>
      <Sidebar />
      {navOpen && <MobileNavDrawer />}

      {/* The column right of the rail: the page (top bar + workspace) and, on a phone, the tab bar under it. */}
      <div className="flex-1 min-w-0 flex flex-col h-full overflow-hidden">
      <main id="main-content" tabIndex={-1} aria-labelledby="page-title"
        className="flex-1 min-h-0 flex flex-col overflow-hidden relative focus:outline-none">

        {/* Top bar: the page's one h1, its group and what it does; the studio's status on the right. */}
        <header className="shell-topbar min-h-[60px] sm:min-h-[68px] flex items-center justify-between gap-3 px-3 sm:px-6 lg:px-8 py-2 shrink-0 z-10">
          <div className="flex items-center gap-1.5 sm:gap-4 min-w-0">
            <button
              type="button"
              onClick={() => setNavOpen(true)}
              aria-label="Open navigation"
              aria-expanded={navOpen}
              className="md:hidden -ml-1.5 w-11 h-11 flex items-center justify-center rounded-input text-ink2 hover:text-ink active:bg-paper3 transition-colors shrink-0"
            >
              <Menu size={20} aria-hidden="true" />
            </button>
            <div className="min-w-0">
              <h1 id="page-title" data-tutorial="nav-clips" className="font-display text-lg sm:text-[1.35rem] text-ink leading-tight truncate">
                {activeNav?.label || 'Synapse AI'}
              </h1>
              {activeNav?.desc && (
                <p className="hidden md:flex items-center gap-2 mt-1 text-xs text-muted min-w-0">
                  <span className="nav-group-label shrink-0">{activeGroup ? activeGroup.label : 'Studio'}</span>
                  <span className="h-3 border-l border-rule2 shrink-0" aria-hidden="true" />
                  <span className="truncate">{activeNav.desc}</span>
                </p>
              )}
            </div>
            {status !== 'idle' && (
              <button type="button" onClick={handleReset} className="btn-quiet px-3 py-1.5 text-xs shrink-0" aria-label="New project">
                <Plus size={14} aria-hidden="true" />
                <span className="hidden sm:inline">New project</span>
              </button>
            )}
          </div>

          <div className="flex items-center gap-2 sm:gap-3 shrink-0">
            {userProfiles.length > 0 && (
              <UserProfileSelector
                profiles={userProfiles}
                selectedUserId={uploadUserId}
                onSelect={setUploadUserId}
                onConnect={isManaged ? handleConnectSocials : undefined}
              />
            )}

            {/* Cloud: minutes meter + account/sign-in. For free users the meter
                opens the upgrade modal — otherwise the only path to a plan is
                failing against the quota wall. */}
            {billingEnabled && isManaged && (
              <UsageMeter onClick={() => {
                if (plan === 'free') { setTopUpInfo({ context: 'upsell' }); setShowTopUp(true); }
                else { window.location.hash = '#/account'; }
              }} />
            )}
            {billingEnabled && isSignedIn && !isManaged && (
              <button type="button" onClick={() => setShowPlanChoice(true)} className="btn-primary px-4 py-2 text-xs">
                Choose a plan
              </button>
            )}
            {billingEnabled && !isSignedIn && (
              <button type="button" onClick={() => setShowLogin(true)} className="btn-ghost px-4 py-2 text-xs">
                Sign in
              </button>
            )}
            {billingEnabled && isSignedIn && <ProfileMenu />}

            {/* The studio's readiness: a real state, so it may carry its colour (with a word and an icon). */}
            {keysMissing ? (
              <button
                type="button"
                onClick={() => (billingEnabled && !isSignedIn ? setShowLogin(true) : goToTab('settings'))}
                className="status-pill status-pill-warn hidden sm:inline-flex"
                title="Configure API keys or choose a plan"
              >
                <AlertTriangle size={13} aria-hidden="true" />
                <span className="hidden md:inline">
                  {!geminiOk && !uploadPostKey
                    ? 'Gemini and Upload-Post keys missing'
                    : !geminiOk
                      ? 'Gemini key missing'
                      : 'Upload-Post key missing'}
                </span>
                <span className="md:hidden">Keys missing</span>
              </button>
            ) : (
              <span className="status-pill hidden sm:inline-flex text-ink2" title="Your API keys are set">
                <span className="status-dot" aria-hidden="true" /> Ready
              </span>
            )}
          </div>
        </header>

        {/* Missing keys: a quiet strip under the top bar on every screen but Settings. */}
        {keysMissing && activeTab !== 'settings' && (
          <div className="mx-3 sm:mx-6 lg:mx-8 mt-3 tray px-4 py-3 flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-4 shrink-0 animate-fade">
            <div className="flex items-start gap-3 min-w-0 flex-1">
              <KeyRound size={16} className="shrink-0 text-warn mt-0.5" aria-hidden="true" />
              <p className="text-sm text-ink2 min-w-0 leading-relaxed">
                <span className="font-medium text-ink">API keys missing.</span>{' '}
                <span className="text-muted">
                  {!geminiOk && !uploadPostKey
                    ? 'Add your Gemini and Upload-Post keys to start making clips.'
                    : !geminiOk
                      ? 'Add your Gemini key to start making clips.'
                      : 'Add your Upload-Post key to start making clips.'}
                </span>
              </p>
            </div>
            <button
              type="button"
              onClick={() => goToTab('settings')}
              className="btn-ghost px-4 py-2 text-xs shrink-0 w-full sm:w-auto"
            >
              Open Settings
            </button>
          </div>
        )}

        {/* Session recovery: announced once, dismissible. */}
        {sessionRecovered && (
          <div role="status" className="mx-3 sm:mx-6 lg:mx-8 mt-3 tray pl-4 pr-1.5 py-1.5 flex items-center justify-between gap-3 animate-fade shrink-0">
            <p className="flex items-center gap-2.5 text-sm text-ink2 min-w-0 py-1.5">
              <RotateCcw size={15} className="text-muted shrink-0" aria-hidden="true" />
              <span className="min-w-0">
                <span className="font-medium text-ink">Session recovered.</span>{' '}
                <span className="text-muted">Your previous work is back where you left it.</span>
              </span>
            </p>
            <button
              type="button"
              onClick={() => setSessionRecovered(false)}
              aria-label="Dismiss"
              className="w-11 h-11 sm:w-9 sm:h-9 flex items-center justify-center rounded-input text-muted hover:text-ink hover:bg-paper2 transition-colors shrink-0"
            >
              <X size={16} aria-hidden="true" />
            </button>
          </div>
        )}

        {/* Included tools (Clip generator, YouTube Studio): non-blocking trial prompt. */}
        {gateThisTab && <TrialGate toolName={TOOL_NAMES[activeTab] || 'this'} />}

        {/* Advanced tools (AI Shorts): BYOK fal.ai + ElevenLabs notice. */}
        {advancedThisTab && <AdvancedBanner needsPlan={needsPlan} onKeys={() => goToTab('settings')} />}

        {/* Workspace: each view scrolls on its own inside it. */}
        <div className="flex-1 min-h-0 overflow-hidden relative z-[1]">

          {/* View: Settings — only what a self-hosted Synapse AI needs: the
              niche, the keys, the Upload-Post connection. Clean hashtags and
              YouTube tags are always on (forced server-side), no toggles. */}
          {activeTab === 'settings' && (
            <div className="h-full overflow-y-auto custom-scrollbar animate-fade">
            <div className="max-w-2xl mx-auto px-4 py-6 sm:p-8 space-y-10 sm:space-y-12 pb-16">
              <p className="tray flex items-start gap-3 px-4 py-3 text-sm text-ink2 leading-relaxed">
                <Shield size={16} className="text-muted shrink-0 mt-0.5" aria-hidden="true" />
                <span>
                  <span className="font-medium text-ink">Your keys stay in this browser.</span>{' '}
                  <span className="text-muted">They are sent to the backend only to run a request, never stored there.</span>
                </span>
              </p>

              <section aria-labelledby="settings-niche" className="space-y-4">
                <div className="flex items-start gap-3">
                  <Hash size={18} className="text-muted shrink-0 mt-1" aria-hidden="true" />
                  <div className="min-w-0">
                    <h2 id="settings-niche" className="font-display text-lg text-ink">Niche and hashtags</h2>
                    <p id="settings-niche-help" className="mt-1 text-sm text-muted leading-relaxed">
                      What your channel posts. Hashtags are researched from the top Shorts of that niche: every post
                      gets the 3-5 about its clip, none in the YouTube title, and YouTube's hidden tags are filled on
                      every upload.
                    </p>
                  </div>
                </div>

                <div className="card p-4 sm:p-6 space-y-5">
                <div>
                <label htmlFor="settings-niche-input" className="block text-sm font-medium text-ink2 mb-2">Your niche</label>
                {results?.niche_guess && niche.trim() === results.niche_guess.trim() && (
                  <p id="settings-niche-guess" className="text-xs text-muted mb-2 flex items-start gap-1.5">
                    <Sparkles size={13} className="shrink-0 mt-px" aria-hidden="true" />
                    Guessed from this video by AI. Correct it if it's off, it'll be remembered either way.
                  </p>
                )}
                <div className="flex flex-col sm:flex-row gap-2">
                  <input
                    id="settings-niche-input"
                    type="text"
                    value={niche}
                    onChange={(e) => setNiche(e.target.value)}
                    className="input-field"
                    placeholder="e.g. Joe Rogan podcast clips"
                    aria-describedby={results?.niche_guess && niche.trim() === results.niche_guess.trim()
                      ? 'settings-niche-help settings-niche-guess' : 'settings-niche-help'}
                  />
                  <button
                    type="button"
                    onClick={async () => {
                      if (!niche.trim() || nicheResearching) return;
                      setNicheResearching(true);
                      setNicheHashtags(null);
                      setNicheError('');
                      try {
                        const data = await apiJson('/api/hashtags/research', {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ niche }),
                        });
                        setNicheHashtags(data.hashtags || []);
                        setNicheHistory(pushNicheHistory(niche));
                      } catch (e) {
                        setNicheError(e.detail || e.message || 'Research failed');
                      } finally {
                        setNicheResearching(false);
                      }
                    }}
                    disabled={!niche.trim() || nicheResearching}
                    className="btn-ghost py-2 px-4 text-sm shrink-0"
                  >
                    {nicheResearching
                      ? <><Loader2 size={14} className="animate-spin" aria-hidden="true" /> Researching…</>
                      : 'See hashtags'}
                  </button>
                </div>
                </div>

                {nicheHistory.filter((n) => n.toLowerCase() !== niche.trim().toLowerCase()).length > 0 && (
                  <div role="group" aria-labelledby="settings-recent-niches">
                    <p id="settings-recent-niches" className="text-xs text-muted mb-2">Recent niches</p>
                    <div className="flex flex-wrap gap-1.5">
                      {nicheHistory
                        .filter((n) => n.toLowerCase() !== niche.trim().toLowerCase())
                        .map((n) => (
                          <button
                            key={n}
                            type="button"
                            onClick={() => setNiche(n)}
                            className="px-2.5 py-1 min-h-[44px] sm:min-h-[30px] rounded border border-rule bg-paper3 text-xs text-ink2 hover:text-ink hover:border-rule2 transition-colors"
                          >
                            {n}
                          </button>
                        ))}
                    </div>
                  </div>
                )}

                {nicheError && (
                  <p className="text-danger text-sm flex items-start gap-1.5" role="alert">
                    <AlertTriangle size={14} className="shrink-0 mt-0.5" aria-hidden="true" />
                    {nicheError}
                  </p>
                )}

                <div aria-live="polite">
                  {nicheHashtags && (
                    <div className="tray p-3.5">
                      <p className="text-xs text-muted mb-2">Hashtags found for this niche</p>
                      {nicheHashtags.length === 0
                        ? <p className="text-sm text-ink2">No hashtags found for this niche.</p>
                        : (
                          <ul className="flex flex-wrap gap-1.5">
                            {nicheHashtags.map((h) => (
                              <li key={h} className="font-mono text-xs text-ink2 bg-paper2 border border-rule rounded px-2 py-0.5">{h}</li>
                            ))}
                          </ul>
                        )}
                    </div>
                  )}
                </div>

                {niche.trim() && (
                  <div className="pt-5 border-t border-rule">
                    <label htmlFor="settings-niche-tags" className="block text-sm font-medium text-ink2 mb-1">
                      Base YouTube tags for “{niche.trim()}”
                    </label>
                    <p id="settings-niche-tags-help" className="text-xs text-muted mb-2">
                      Comma-separated. Added after each clip's own topics.
                    </p>
                    <textarea
                      id="settings-niche-tags"
                      value={nicheTagsDraft}
                      onChange={(e) => { setNicheTagsDraft(e.target.value); setNicheTagsSaved(false); }}
                      rows={3}
                      aria-describedby="settings-niche-tags-help"
                      className="input-field font-mono text-xs leading-relaxed"
                      placeholder="podcast, podcast clips, joe rogan, jre, mental health, science…"
                    />
                    <div className="flex flex-wrap items-center gap-3 mt-2">
                      <button
                        type="button"
                        onClick={async () => {
                          setNicheTagsSaved(await savePublishSettings({ niche: niche.trim(), niche_tags: nicheTagsDraft }));
                        }}
                        className="btn-ghost py-2 px-4 text-sm"
                      >
                        Save tags
                      </button>
                      <span className="text-xs text-ok inline-flex items-center gap-1.5" aria-live="polite">
                        {nicheTagsSaved && <><Check size={13} aria-hidden="true" /> Saved</>}
                      </span>
                    </div>
                  </div>
                )}
                </div>
              </section>

              {isManaged ? (
                <section aria-labelledby="settings-plan" className="space-y-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex items-start gap-3 min-w-0">
                      <Shield size={18} className="text-muted shrink-0 mt-1" aria-hidden="true" />
                      <div className="min-w-0">
                        <h2 id="settings-plan" className="font-display text-lg text-ink">Included in your plan</h2>
                        <p className="mt-1 text-sm text-muted leading-relaxed">
                          Your plan includes the <strong className="font-medium text-ink2">Clip generator</strong> and{' '}
                          <strong className="font-medium text-ink2">YouTube Studio</strong>, fully managed: no API keys
                          required. AI Shorts and dubbing use your own fal.ai and ElevenLabs keys (below).
                        </p>
                      </div>
                    </div>
                    <span className="badge-ok shrink-0 mt-1">Managed</span>
                  </div>
                  <div className="card p-4 sm:p-6">
                    <p className="text-sm text-ink2 mb-4">Connect your social accounts to publish directly.</p>
                    <div className="flex flex-col sm:flex-row gap-2">
                      <button type="button" onClick={handleConnectSocials} className="btn-primary py-2 px-4 text-sm">
                        <Share2 size={16} aria-hidden="true" /> Connect social accounts
                      </button>
                      <button type="button" onClick={handleOpenCalendar} className="btn-ghost py-2 px-4 text-sm">
                        <Calendar size={16} aria-hidden="true" /> Content calendar
                        <span className="sr-only">(opens in a new tab)</span>
                      </button>
                    </div>
                  </div>
                </section>
              ) : billingEnabled ? (
                <section aria-labelledby="settings-plan" className="space-y-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex items-start gap-3 min-w-0">
                      <Sparkles size={18} className="text-muted shrink-0 mt-1" aria-hidden="true" />
                      <div className="min-w-0">
                        <h2 id="settings-plan" className="font-display text-lg text-ink">Choose your plan</h2>
                        <p className="mt-1 text-sm text-muted leading-relaxed">
                          Generate shorts with zero setup, no API keys needed. Start free with 20 min/month, or go paid
                          from $12/mo. Cancel anytime.
                        </p>
                      </div>
                    </div>
                    <span className="readout shrink-0 mt-1.5">Free plan available</span>
                  </div>
                  <div className="card p-4 sm:p-6">
                    <button type="button" onClick={() => setShowPlanChoice(true)} className="btn-accent py-2 px-5 text-sm w-full sm:w-auto">
                      <Sparkles size={16} aria-hidden="true" /> Choose a plan
                    </button>
                  </div>
                </section>
              ) : (
                <>
              <KeyInput onKeySet={setApiKey} savedKey={apiKey} />

              <section aria-labelledby="settings-upload-post" className="space-y-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex items-start gap-3 min-w-0">
                    <Share2 size={18} className="text-muted shrink-0 mt-1" aria-hidden="true" />
                    <div className="min-w-0">
                      <h2 id="settings-upload-post" className="font-display text-lg text-ink">Publishing with Upload-Post</h2>
                      <p id="settings-upload-post-help" className="mt-1 text-sm text-muted leading-relaxed">
                        Sends your clips to TikTok, Instagram Reels and YouTube Shorts. Free tier, no card.
                      </p>
                    </div>
                  </div>
                  {userProfiles.length > 0
                    ? <span className="badge-ok shrink-0 mt-1"><Check size={11} aria-hidden="true" /> Connected</span>
                    : <span className="badge-warn shrink-0 mt-1">Needed to publish</span>}
                </div>

                <div className="card p-4 sm:p-6 space-y-4">
                <div>
                <label htmlFor="settings-upload-post-key" className="block text-sm font-medium text-ink2 mb-2">API key</label>
                <div className="flex flex-col sm:flex-row gap-2">
                  <input
                    id="settings-upload-post-key"
                    type="password"
                    value={uploadPostKey}
                    onChange={(e) => setUploadPostKey(e.target.value)}
                    className="input-field font-mono"
                    placeholder="ey..."
                    autoComplete="off"
                    spellCheck={false}
                    aria-describedby="settings-upload-post-help"
                  />
                  <button type="button" onClick={fetchUserProfiles} disabled={connectStatus === 'loading'} className="btn-primary py-2 px-5 text-sm shrink-0">
                    {connectStatus === 'loading'
                      ? <><Loader2 size={14} className="animate-spin" aria-hidden="true" /> Connecting…</>
                      : 'Connect'}
                  </button>
                </div>
                </div>
                {connectStatus && connectStatus !== 'loading' && (
                  <p className={`text-sm flex items-start gap-1.5 ${connectStatus.ok ? 'text-ok' : 'text-danger'}`}
                    role={connectStatus.ok ? 'status' : 'alert'}>
                    {connectStatus.ok
                      ? <Check size={14} className="shrink-0 mt-0.5" aria-hidden="true" />
                      : <AlertTriangle size={14} className="shrink-0 mt-0.5" aria-hidden="true" />}
                    {connectStatus.msg}
                  </p>
                )}
                {userProfiles.length > 0 ? (() => {
                  const active = userProfiles.find((p) => p.username === uploadUserId) || userProfiles[0];
                  const connected = active?.connected || [];
                  return (
                    <dl className="tray px-4 py-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
                      <dt className="text-muted">Posting as</dt>
                      <dd className="text-ink2 min-w-0 truncate">{active?.username}</dd>
                      <dt className="text-muted">Networks</dt>
                      <dd className="min-w-0">
                        {connected.length
                          ? <span className="text-ink2">{connected.join(', ')} connected</span>
                          : <span className="text-warn inline-flex items-center gap-1.5"><AlertTriangle size={13} aria-hidden="true" /> No social account connected on this profile</span>}
                      </dd>
                    </dl>
                  );
                })() : (
                  // The how-to only matters until the account is connected.
                  <div className="pt-4 border-t border-rule">
                    <p id="settings-upload-post-steps" className="text-xs text-muted mb-2">Get a key in three steps on upload-post.com</p>
                    <ol aria-labelledby="settings-upload-post-steps" className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-sm">
                      {[
                        ['Sign in', 'Create the account', 'https://app.upload-post.com/login'],
                        ['Profiles', 'Connect your socials', 'https://app.upload-post.com/manage-users'],
                        ['API key', 'Generate it, paste it above', 'https://app.upload-post.com/api-keys'],
                      ].map(([step, what, href]) => (
                        <li key={step}>
                          <a href={href} target="_blank" rel="noopener noreferrer"
                            className="card-hover h-full min-h-[44px] p-3 tray flex items-start justify-between gap-2 hover:bg-paper2">
                            <span className="flex flex-col gap-0.5 min-w-0">
                              <span className="text-ink font-medium">{step}</span>
                              <span className="text-xs text-muted">{what}</span>
                            </span>
                            <ExternalLink size={13} className="text-muted shrink-0 mt-1" aria-hidden="true" />
                            <span className="sr-only">(opens in a new tab)</span>
                          </a>
                        </li>
                      ))}
                    </ol>
                  </div>
                )}
                </div>
              </section>

                </>
              )}

              {/* fal.ai + ElevenLabs: AI Shorts actors and voices, and dubbing. */}
              <section aria-labelledby="settings-ai-shorts" className="space-y-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex items-start gap-3 min-w-0">
                    <Sparkles size={18} className="text-muted shrink-0 mt-1" aria-hidden="true" />
                    <div className="min-w-0">
                      <h2 id="settings-ai-shorts" className="font-display text-lg text-ink">AI Shorts and dubbing</h2>
                      <p className="mt-1 text-sm text-muted leading-relaxed">
                        <strong className="font-medium text-ink2">fal.ai</strong> films the AI actors of AI Shorts;{' '}
                        <strong className="font-medium text-ink2">ElevenLabs</strong> gives them a voice and translates
                        your clips. Billed by those providers (~$0.65-2 per AI Short).
                      </p>
                    </div>
                  </div>
                  <span className="chip-byok shrink-0 mt-1.5" title="Bring your own keys">BYOK</span>
                </div>
                <div className="card divide-y divide-rule">
                  {[
                    { id: 'fal', label: 'fal.ai API key', value: falKey, set: setFalKey, saved: falSaved, setSaved: setFalSaved,
                      store: 'falKey_v1', placeholder: 'fal_...', href: 'https://fal.ai/dashboard/keys' },
                    { id: 'elevenlabs', label: 'ElevenLabs API key', value: elevenLabsKey, set: setElevenLabsKey, saved: elevenLabsSaved,
                      setSaved: setElevenLabsSaved, store: 'elevenLabsKey_v1', placeholder: 'sk_...', href: 'https://elevenlabs.io/app/settings/api-keys' },
                  ].map((k) => (
                    <div key={k.id} className="p-4 sm:p-6">
                      <div className="flex items-baseline justify-between gap-3 mb-2">
                        <label htmlFor={`settings-key-${k.id}`} className="text-sm font-medium text-ink2">{k.label}</label>
                        <a href={k.href} target="_blank" rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-xs text-cobalt underline underline-offset-2 hover:text-ink transition-colors">
                          Get a key <ExternalLink size={12} aria-hidden="true" />
                          <span className="sr-only">(opens in a new tab)</span>
                        </a>
                      </div>
                      <div className="flex flex-col sm:flex-row gap-2">
                        <input
                          id={`settings-key-${k.id}`}
                          type="password"
                          value={k.value}
                          onChange={(e) => k.set(e.target.value)}
                          className="input-field font-mono"
                          placeholder={k.placeholder}
                          autoComplete="off"
                          spellCheck={false}
                        />
                        <button
                          type="button"
                          onClick={() => {
                            if (k.value) {
                              localStorage.setItem(k.store, encrypt(k.value));
                              k.setSaved(true);
                              setTimeout(() => k.setSaved(false), 2000);
                            }
                          }}
                          className={`btn-ghost py-2 px-5 text-sm shrink-0 ${k.saved ? '!text-ok' : ''}`}
                        >
                          {k.saved ? <><Check size={14} aria-hidden="true" /> Saved</> : 'Save'}
                        </button>
                      </div>
                      <span className="sr-only" aria-live="polite">{k.saved ? `${k.label} saved.` : ''}</span>
                    </div>
                  ))}
                </div>
              </section>
            </div>
            </div>
          )}

          {/* View: SaaS Shorts */}
          {activeTab === 'saasshorts' && (
            <SaaShortsTab geminiApiKey={apiKey} elevenLabsKey={elevenLabsKey} falKey={falKey} uploadPostKey={uploadPostKey} uploadUserId={uploadUserId} managed={isManaged} />
          )}

          {/* View: UGC Gallery */}
          {activeTab === 'ugc-gallery' && (
            <div className="h-full overflow-y-auto custom-scrollbar animate-fade">
              <div className="max-w-7xl mx-auto px-4 py-6 sm:p-8">
                <UGCGallery />
              </div>
            </div>
          )}

          {/* View: History */}
          {activeTab === 'history' && (
            <div className="h-full overflow-y-auto custom-scrollbar animate-fade">
              <div className="max-w-7xl mx-auto px-4 py-6 sm:p-8">
                <HistoryTab onReopenProject={restoreProject} billingEnabled={billingEnabled} />
              </div>
            </div>
          )}

          {/* View: Viral Clip Reworker */}
          {activeTab === 'reworker' && (
            <div className="h-full overflow-y-auto custom-scrollbar animate-fade">
              <ReworkerTab geminiApiKey={apiKey} elevenLabsKey={elevenLabsKey} onDone={restoreProject} />
            </div>
          )}

          {/* View: Notion pictures */}
          {activeTab === 'notions' && !billingEnabled && (
            <div className="h-full overflow-y-auto custom-scrollbar animate-fade">
              <NotionLibrary />
            </div>
          )}

          {/* View: B-roll images */}
          {activeTab === 'broll-gallery' && !billingEnabled && (
            <div className="h-full overflow-y-auto custom-scrollbar animate-fade">
              <BrollGallery />
            </div>
          )}

          {/* View: Publish plan */}
          {activeTab === 'publish-plan' && (
            <div className="h-full overflow-y-auto custom-scrollbar animate-fade">
              <div className="max-w-7xl mx-auto px-4 py-6 sm:p-8">
                <PublishPlanTab
                  uploadPostKey={uploadPostKey}
                  uploadUserId={uploadUserId}
                  profiles={userProfiles}
                  isManaged={isManaged}
                  lastNiche={niche}
                  onNicheUsed={(n, profile) => {
                    setNiche(n);
                    setNicheHistory(pushNicheHistory(n));
                    if (profile) rememberNicheProfile(n, profile);
                  }}
                />
              </div>
            </div>
          )}

          {/* View: Story channel */}
          {activeTab === 'story' && (
            <div className="h-full overflow-y-auto custom-scrollbar animate-fade">
              <StoryTab geminiApiKey={apiKey} onOpenProject={restoreProject} />
            </div>
          )}

          {/* View: Viral finder */}
          {activeTab === 'viral-finder' && (
            <div className="h-full overflow-y-auto custom-scrollbar animate-fade">
              <div className="max-w-7xl mx-auto px-4 py-6 sm:p-8">
                <ViralFinderTab />
              </div>
            </div>
          )}

          {/* View: YouTube Studio (the component owns its scroll pane) */}
          {activeTab === 'thumbnails' && (
            <ThumbnailStudio
              geminiApiKey={apiKey}
              uploadPostKey={uploadPostKey}
              uploadUserId={uploadUserId}
              managed={isManaged}
              onOpenSettings={() => goToTab('settings')}
              onCreateClips={(sessionId) => {
                setActiveTab('dashboard');
                // The Studio source is the user's own upload, published to their
                // own channel; the handover carries that same attestation.
                handleProcess({ type: 'thumbnail_session', payload: sessionId, acknowledged: true });
              }}
            />
          )}

          {/* View: Gallery */}
          {/* {activeTab === 'gallery' && (
            <Gallery />
          )} */}

          {/* View: Dashboard (Idle) */}
          {activeTab === 'dashboard' && status === 'idle' && (
            <div className="h-full overflow-y-auto custom-scrollbar animate-fade">
              <div className="min-h-full flex flex-col justify-center px-4 py-5 sm:p-8 lg:px-12 lg:py-12">
              {/* The studio's front page. Phone: a compact headline, then the
                  drop zone straight away (the whole point of the screen), then
                  the extras. Desktop: headline and extras on the left over a
                  faint neuron, the drop zone as the feature on the right. */}
              <div className="relative w-full max-w-6xl mx-auto grid gap-5 sm:gap-8 lg:gap-x-14 lg:gap-y-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:grid-rows-[auto_1fr] items-start">

                {/* The synapse motif: one neuron in white hairlines, its nucleus the signal. Static: nothing is running. */}
                <div className="hidden lg:block relative lg:col-start-1 lg:row-start-1 lg:row-span-2 self-stretch pointer-events-none" aria-hidden="true">
                  <svg className="neural-field text-ink" viewBox="0 0 400 520" preserveAspectRatio="xMaxYMax meet" fill="none">
                    <g stroke="currentColor" strokeWidth="1.2" strokeLinecap="round">
                      <path d="M300 340 C 290 290, 252 258, 232 210 S 222 128, 182 86" />
                      <path d="M232 210 C 204 200, 164 210, 132 190" />
                      <path d="M300 340 C 330 300, 352 262, 392 240" />
                      <path d="M350 270 C 362 230, 352 190, 372 150" />
                      <path d="M300 340 C 340 360, 372 390, 400 398" />
                      <path d="M300 340 C 270 390, 222 420, 172 440 S 82 478, 22 520" />
                      <path d="M222 420 C 212 458, 232 488, 222 520" />
                      <path d="M300 340 C 302 390, 322 440, 312 520" />
                    </g>
                    <circle cx="300" cy="340" r="15" stroke="currentColor" strokeWidth="1.4" />
                    <g className="fill-ink">
                      <circle cx="182" cy="86" r="2.5" />
                      <circle cx="132" cy="190" r="2" />
                      <circle cx="372" cy="150" r="2" />
                      <circle cx="392" cy="240" r="2" />
                    </g>
                    <circle cx="300" cy="340" r="5.5" className="fill-vermilion" />
                  </svg>
                </div>

                {/* Headline */}
                <div className="relative lg:col-start-1 lg:row-start-1 space-y-2.5 sm:space-y-4 lg:pt-6">
                  <p className="readout hidden sm:block">New clip</p>
                  <h2 className="page-title">
                    Turn one long video into <span className="ink-underline">shorts</span>
                  </h2>
                  <p className="page-lede text-sm sm:text-[0.95rem]">
                    Drop a file or paste a link. The AI finds the strongest moments and cuts them into
                    captioned vertical clips, ready to review and publish.
                  </p>
                </div>

                {/* The drop zone: the feature of the page. */}
                <div className="relative min-w-0 lg:col-start-2 lg:row-start-1 lg:row-span-2">
                  <MediaInput
                    onProcess={handleProcess}
                    isProcessing={status === 'processing'}
                    publishProfiles={userProfiles}
                    defaultProfile={uploadUserId}
                    canAutoPublish={!billingEnabled && !!uploadPostKey && !!(uploadUserId || userProfiles.length)}
                  />
                </div>

                {/* Extras: where clips go, and the agent route. */}
                <div className="relative lg:col-start-1 lg:row-start-2 space-y-4 lg:pt-4 lg:border-t lg:border-rule">
                  <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-muted">
                    <span className="readout">Publishes to</span>
                    <span className="flex items-center gap-1.5"><Youtube size={16} aria-hidden="true" /> YouTube</span>
                    <span className="flex items-center gap-1.5"><Instagram size={16} aria-hidden="true" /> Instagram</span>
                    <span className="flex items-center gap-1.5"><TikTokIcon size={16} className="shrink-0" /> TikTok</span>
                  </div>
                  {/* The same pipeline is an MCP server: point people at the
                      one place that explains how to drive it from an agent —
                      the cloud Account page (self-host has no such section). */}
                  {!tutorialLock && billingEnabled && (
                  <p className="text-sm text-muted">
                    Or let an agent do it:{' '}
                    <a
                      href="#/account"
                      className="text-cobalt underline underline-offset-2 hover:text-ink transition-colors"
                    >
                      connect Claude, ChatGPT or n8n
                    </a>
                  </p>
                  )}
                </div>
              </div>
              </div>
            </div>
          )}

          {/* View: Processing / Results (Split View) */}
          {activeTab === 'plus' && status === 'idle' && (
            <div className="h-full overflow-y-auto custom-scrollbar">
              <PlusPanel
                onProcess={handleProcess}
                isProcessing={status === 'processing'}
                publishProfiles={userProfiles}
                defaultProfile={uploadUserId}
                canAutoPublish={!billingEnabled && !!uploadPostKey && !!(uploadUserId || userProfiles.length)}
                uploadPostKey={uploadPostKey}
                geminiApiKey={apiKey}
                onProfileChange={setPlusProfile}
              />
            </div>
          )}

          {(activeTab === 'dashboard' || activeTab === 'plus') && (status === 'processing' || status === 'complete' || status === 'error') && (
            <div className="h-full flex flex-col md:flex-row gap-4 md:gap-5 p-4 sm:p-5 md:p-6 overflow-y-auto md:overflow-y-hidden custom-scrollbar animate-fade">

              {/* Left panel: the job sheet. While the job runs it is THE card of
                  the view: what stage it is in (the synapse pathway), the source
                  it is reading, who is thinking, and the raw log underneath. */}
              <section
                aria-labelledby="job-panel-title"
                className={`${status === 'complete' ? 'w-full md:w-[30%] lg:w-[25%]' : 'w-full md:w-[55%] lg:w-[60%]'} ${jobPanelFolded ? 'hidden' : ''} md:h-full flex flex-col shrink-0 md:shrink min-w-0 ${status === 'processing' ? 'card-print' : 'card'} p-4 sm:p-6 md:overflow-y-auto custom-scrollbar transition-[width] duration-500 ease-out`}
              >
                <header className="mb-5 sm:mb-6 flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    {status === 'processing' ? (
                      <p className="readout">Live job</p>
                    ) : status === 'complete' ? (
                      <p className="badge-ok"><Check size={11} aria-hidden="true" /> Complete</p>
                    ) : (
                      <p className="badge-danger"><AlertTriangle size={11} aria-hidden="true" /> Failed</p>
                    )}
                    <h2 id="job-panel-title" className="font-display text-xl sm:text-2xl text-ink leading-tight mt-2">
                      {status === 'processing' ? 'Cutting your clips' : status === 'complete' ? 'Job complete' : 'The job didn’t finish'}
                    </h2>
                  </div>
                  {status === 'processing' && jobId && (
                    <button type="button" onClick={handleStopWork} disabled={stopping}
                      className="btn-danger shrink-0 px-3 py-2 text-xs"
                      title="Stops the job now (transcription, analysis, rendering). Clips already finished stay.">
                      <Square size={11} aria-hidden="true" className="fill-current" />
                      {stopping ? 'Stopping…' : 'Stop job'}
                    </button>
                  )}
                </header>

                {/* The real progress (app.py _job_progress) drawn as the pipeline's pathway. */}
                {status === 'processing' && <JobProgressBar progress={jobProgress} pipeline="clips" />}

                {(processingMedia || status === 'processing') && (
                  <div className={`grid gap-4 mb-5 ${processingMedia && status === 'processing'
                    ? 'items-start sm:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)] md:grid-cols-1 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]'
                    : ''}`}>
                    {/* The source, framed as a plate (true black, hairline). */}
                    {processingMedia && (
                      <ProcessingAnimation
                        media={processingMedia}
                        isComplete={status === 'complete'}
                        syncedTime={syncedTime}
                        isSyncedPlaying={isSyncedPlaying}
                        syncTrigger={syncTrigger}
                        progress={jobProgress}
                      />
                    )}

                    {status === 'processing' && (
                      <div className="space-y-3 min-w-0">
                        {/* Who is thinking right now (ai_brain.py: Claude first, Gemini as fallback). */}
                        <BrainBadge logs={logs} />

                        {/* Phones only. The log below starts collapsed at this
                            size, so the tail of it is said here: the real answer
                            to "what is it doing right now". */}
                        <div className="sm:hidden tray px-3.5 py-3 min-w-0">
                          <p className="readout">Latest log line</p>
                          <p className="mt-1 font-mono text-xs text-ink2 leading-relaxed break-words">
                            {logs.length ? (logs.filter(isKeyLog).slice(-1)[0] || logs[logs.length - 1]) : 'Starting up…'}
                          </p>
                        </div>

                        {/* The render is dead time: the user is watching a progress bar
                            with nothing to do, so this is where the one star ask goes. */}
                        <StarBanner message="Got a minute while this renders?" />
                      </div>
                    )}
                  </div>
                )}

                {/* The pipeline log */}
                <div className={`tray overflow-hidden flex flex-col ${status === 'complete' ? `min-h-0 ${logsVisible ? 'h-56' : 'h-auto'}` : `flex-1 ${logsVisible ? 'min-h-[200px] sm:min-h-[240px] max-h-[70vh] md:max-h-none' : 'min-h-0 flex-none'}`}`}>
                  <button
                    type="button"
                    onClick={() => setLogsVisible(!logsVisible)}
                    aria-expanded={logsVisible}
                    aria-controls="job-log"
                    className="w-full min-h-[44px] px-4 py-2.5 flex items-center justify-between gap-3 shrink-0 text-left hover:bg-paper2 transition-colors"
                  >
                    <span className="flex items-center gap-2 text-sm font-medium text-ink">
                      <Terminal size={14} aria-hidden="true" className="text-muted" />
                      Pipeline log
                    </span>
                    <span className="flex items-center gap-2 text-muted">
                      {!logsVisible && logs.length > 0 && (
                        <span className="readout">{logs.filter(isKeyLog).length} key lines</span>
                      )}
                      <ChevronDown size={16} aria-hidden="true" className={`transition-transform duration-200 ${logsVisible ? 'rotate-180' : ''}`} />
                    </span>
                  </button>
                  {logsVisible && (
                    <div id="job-log" className="flex-1 min-h-0 flex flex-col border-t border-rule">
                      <div className="shrink-0 flex flex-wrap items-center justify-between gap-2 px-4 py-2 border-b border-rule">
                        <div role="group" aria-label="Log detail" className="inline-flex gap-0.5 rounded-input border border-rule2 p-0.5">
                          {[['key', 'Key lines'], ['all', 'Everything']].map(([v, label]) => (
                            <button key={v} type="button" onClick={() => setLogMode(v)} aria-pressed={logMode === v}
                              className={`px-3 py-1 min-h-[30px] [@media(pointer:coarse)]:min-h-[40px] rounded-[6px] text-xs font-medium transition-colors ${logMode === v ? 'bg-ink text-paper' : 'text-muted hover:text-ink'}`}>
                              {label}
                            </button>
                          ))}
                        </div>
                        <span className="readout">
                          {logMode === 'key' ? `${logs.filter(isKeyLog).length} of ${logs.length}` : `${logs.length} lines`}
                        </span>
                      </div>
                      {/* Not announced line by line: the stage above already is. */}
                      <div
                        role="log"
                        aria-live="off"
                        aria-label="Job log"
                        tabIndex={0}
                        className="flex-1 min-h-0 overflow-y-auto custom-scrollbar px-4 py-3 font-mono text-xs leading-relaxed text-ink2 space-y-1"
                      >
                        {(logMode === 'key' ? logs.filter(isKeyLog) : logs).map((log, i) => (
                          <p key={i} className={`flex gap-3 min-w-0 ${log.toLowerCase().includes('error') ? 'text-danger' : ''}`}>
                            <span aria-hidden="true" className="hidden sm:inline min-w-[2rem] shrink-0 text-right text-muted tabular-nums select-none">{i + 1}</span>
                            <span className="min-w-0 [overflow-wrap:anywhere]">{log}</span>
                          </p>
                        ))}
                        {status === 'processing' && (
                          <span aria-hidden="true" className="inline-block sm:ml-11 h-3.5 w-1.5 align-middle bg-ink2 animate-pulse" />
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </section>

              {/* Right panel: the clips, best first, arriving as they render.
                  No sheet around it: the clip cards are the sheets. */}
              <section
                aria-labelledby="results-title"
                className={`${jobPanelFolded ? 'w-full' : status === 'complete' ? 'w-full md:w-[70%] lg:w-[75%]' : 'w-full md:w-[45%] lg:w-[40%]'} md:h-full flex flex-col shrink-0 md:shrink min-w-0 transition-[width] duration-500 ease-out`}
              >
                <header className="shrink-0 pb-4 mb-4 sm:mb-5 border-b border-rule">
                  <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
                    <div className="min-w-0">
                      <p className="readout">{status === 'processing' ? 'Arriving as they render' : 'Best first'}</p>
                      <h2 id="results-title" className="font-display text-xl sm:text-2xl text-ink leading-tight mt-1.5">
                        Generated shorts
                      </h2>
                    </div>
                    {results?.clips?.length > 0 && (
                      <dl className="flex items-end gap-6">
                        <div>
                          <dt className="readout">To post</dt>
                          <dd className="font-quote text-4xl text-ink leading-none tabular-nums mt-1">
                            {results.clips.length - postedCount}
                          </dd>
                        </div>
                        {postedCount > 0 && (
                          <div>
                            <dt className="readout">Posted</dt>
                            <dd className="font-quote text-4xl text-muted leading-none tabular-nums mt-1">{postedCount}</dd>
                          </div>
                        )}
                      </dl>
                    )}
                  </div>

                  {(postedCount > 0 || (results?.cost_analysis && !isManaged) || (status === 'complete' && !processingMedia) || (results?.clips?.length > 0 && status === 'complete')) && (
                    <div className="mt-4 flex flex-wrap items-center gap-2">
                      {postedCount > 0 && (
                        <button
                          type="button"
                          onClick={() => setShowPosted((v) => !v)}
                          className="btn-quiet px-3 py-2 text-xs"
                          title="Posted clips leave the project so they can't be posted twice"
                        >
                          {showPosted ? 'Hide posted clips' : 'Show posted clips'}
                        </button>
                      )}
                      {status === 'complete' && !processingMedia && (
                        <button
                          type="button"
                          onClick={() => setShowJobPanel((v) => !v)}
                          className="btn-quiet px-3 py-2 text-xs"
                          title="Show the job's log"
                        >
                          <Terminal size={13} aria-hidden="true" />
                          {showJobPanel ? 'Hide job log' : 'Show job log'}
                        </button>
                      )}
                      {results?.cost_analysis && !isManaged && (
                        <span className="readout px-2.5 py-1.5 rounded-input border border-rule" title={`Input: ${results.cost_analysis.input_tokens} | Output: ${results.cost_analysis.output_tokens}`}>
                          Gemini · ${results.cost_analysis.total_cost.toFixed(5)}
                        </span>
                      )}
                      {results?.clips?.length > 0 && status === 'complete' && (
                        <div className="w-full sm:w-auto sm:ml-auto grid grid-cols-2 sm:flex gap-2">
                          <button
                            type="button"
                            onClick={handleDownloadAll}
                            disabled={downloadingAll}
                            className="btn-ghost px-3.5 py-2 text-xs"
                            title="Download all clips as a ZIP"
                          >
                            {downloadingAll
                              ? <><Loader2 size={14} className="animate-spin" aria-hidden="true" />Zipping…</>
                              : <><Download size={14} aria-hidden="true" />Download all</>}
                          </button>
                          <button
                            type="button"
                            onClick={() => setShowScheduleWeek(true)}
                            className="btn-primary px-4 py-2 text-xs"
                          >
                            <Calendar size={14} aria-hidden="true" />
                            Schedule clips
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </header>

                {status === 'complete' && results?.clips?.length > 0 && (
                  <div className="shrink-0 mb-4 space-y-2.5">
                    {/* Peak-moment upsell: they just SAW their clips — sell while
                        they're proud of the result, before asking for stars. */}
                    {plan === 'free' && (
                      <button
                        type="button"
                        onClick={() => { setTopUpInfo({ context: 'upsell' }); setShowTopUp(true); }}
                        className="w-full text-left flex flex-col sm:flex-row sm:items-center gap-1.5 sm:gap-4 px-4 py-3 rounded-card border border-rule2 bg-paper2 hover:border-ink/40 hover:bg-paper3 transition-colors"
                      >
                        <span className="min-w-0 flex-1 text-sm leading-relaxed">
                          <span className="font-medium text-ink">Like these clips?</span>{' '}
                          <span className="text-muted">They carry a watermark and are deleted after 7 days.</span>
                        </span>
                        <span className="shrink-0 text-sm font-medium text-ink">
                          Keep them forever <span aria-hidden="true">→</span>
                        </span>
                      </button>
                    )}
                    {/* Distribution nudge at the same peak: clips on screen,
                        publishing them is one connect away. Hidden once any
                        network is linked or the user dismisses it. */}
                    {showSocialNudge && (
                      <div className="tray px-4 py-3 flex items-start sm:items-center gap-2">
                        <div className="min-w-0 flex-1 flex flex-col sm:flex-row sm:items-center gap-3">
                          <p className="min-w-0 flex-1 text-sm leading-relaxed">
                            <span className="font-medium text-ink">Publish these clips straight from here.</span>{' '}
                            <span className="text-muted">Connect your YouTube, TikTok or Instagram once — after that every clip is one click from posted.</span>
                          </p>
                          <button
                            type="button"
                            onClick={() => { track('SocialNudgeConnect'); handleConnectSocials(); }}
                            className="btn-ghost shrink-0 self-start sm:self-auto px-3.5 py-2 text-xs"
                          >
                            Connect socials <span aria-hidden="true">→</span>
                          </button>
                        </div>
                        <button
                          type="button"
                          onClick={() => {
                            track('SocialNudgeDismissed');
                            setSocialNudgeDismissed(true);
                            try { localStorage.setItem('os_social_nudge_dismissed', '1'); } catch (_) { /* ignore */ }
                          }}
                          aria-label="Dismiss"
                          className="shrink-0 -mr-2 -mt-1.5 sm:my-0 h-11 w-11 sm:h-9 sm:w-9 inline-flex items-center justify-center rounded-input text-muted hover:text-ink hover:bg-paper2 transition-colors"
                        >
                          <X size={16} aria-hidden="true" />
                        </button>
                      </div>
                    )}
                    {/* Self-host only: cloud archives clips to the video library,
                        here they really are gone once the retention sweep runs. */}
                    {!billingEnabled && jobRetentionSeconds > 0 && (
                      <p className="tray px-4 py-3 text-sm leading-relaxed">
                        <span className="text-ink">Clips are kept for {formatRetention(jobRetentionSeconds)}, then deleted.</span>{' '}
                        <span className="text-muted">
                          Download what you want to keep, or raise <code className="font-mono text-xs text-ink2">JOB_RETENTION_SECONDS</code> in your env.
                        </span>
                      </p>
                    )}
                  </div>
                )}

                <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar -mx-1 px-1 pt-1">
                  {results && results.clips && results.clips.length > 0 ? (
                    visibleClips.length === 0 ? (
                      <div className="tray px-6 py-14 text-center">
                        <p className="text-sm font-medium text-ink">Every clip of this project is posted.</p>
                        <p className="text-sm text-muted mt-1">Nothing left to publish.</p>
                      </div>
                    ) : (
                    <ul className="grid gap-4 sm:gap-5 pb-10 [grid-template-columns:repeat(auto-fill,minmax(min(100%,28rem),1fr))]">
                      {visibleClips.map(({ clip, index: i }) => (
                        <li key={`${jobId}-${i}-${clip.video_url || ''}`} className={`min-w-0 ${clip.published ? 'relative' : ''}`}>
                          {clip.published && (
                            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 mb-2 px-3 py-1.5 rounded-input border border-rule bg-paper3 text-xs">
                              <span className="inline-flex items-center gap-1.5 font-medium text-ok">
                                <CheckCircle2 size={13} aria-hidden="true" />
                                {clip.published.via === 'manual' ? 'Posted by hand' : clip.published.scheduled_for ? `Scheduled · ${clip.published.scheduled_for.slice(0, 16).replace('T', ' ')}` : 'Posted'}
                              </span>
                              <button
                                type="button"
                                onClick={() => restoreClip(i)}
                                className="min-h-[32px] [@media(pointer:coarse)]:min-h-[44px] text-ink2 hover:text-ink underline underline-offset-2"
                              >
                                Put back in project
                              </button>
                            </div>
                          )}
                        <ResultCard
                          clip={clip}
                          index={i}
                          jobId={jobId}
                          onEditClip={(index) => setEditingClip(index)}
                          plusProfileId={activeTab === 'plus' ? plusProfile?.id : null}
                          onReframeClip={(index) => setReframingClip(index)}
                          initialState={projectState?.clips?.find((c) => c.index === i) || null}
                          onStateChange={handleClipStateChange}
                          durable={durableClips[i]}
                          uploadPostKey={uploadPostKey}
                          uploadUserId={postingProfile}
                          geminiApiKey={apiKey}
                          elevenLabsKey={elevenLabsKey}
                          niche={proposedNiche}
                          onNicheUsed={(n) => saveProjectNiche(n, projectProfile || undefined)}
                          isManaged={isManaged}
                          connectedPlatforms={(userProfiles.find((p) => p.username === postingProfile) || userProfiles[0])?.connected ?? null}
                          onConnectSocials={isManaged ? handleConnectSocials : null}
                          onPlay={(time) => handleClipPlay(time)}
                          onPause={handleClipPause}
                          onBulkSubtitle={handleBulkSubtitles}
                          clipCount={results.clips.length}
                          bulkProgress={bulkSub}
                          onPublished={refreshResults}
                        />
                        </li>
                      ))}
                    </ul>
                    )
                  ) : (
                    status === 'processing' ? (
                      <div className="tray h-full min-h-[180px] flex flex-col items-center justify-center gap-3 text-center px-6 py-10">
                        <span aria-hidden="true" className="neural-node h-2 w-2 rounded-full bg-muted" />
                        <p className="text-sm font-medium text-ink">Waiting for the first clip</p>
                        <p className="text-sm text-muted max-w-[32ch] leading-snug">
                          They appear here one by one as each finishes rendering.
                        </p>
                      </div>
                    ) : status === 'error' ? (
                      <div role="alert" className="tray h-full min-h-[160px] flex flex-col items-center justify-center gap-2 text-center px-6 py-10">
                        <AlertTriangle size={20} aria-hidden="true" className="text-danger" />
                        <p className="text-sm font-medium text-ink">Generation failed.</p>
                        {logs.length > 0 && (
                          <p className="font-mono text-xs text-ink2 leading-relaxed max-w-prose [overflow-wrap:anywhere]">
                            {logs[logs.length - 1]}
                          </p>
                        )}
                      </div>
                    ) : null
                  )}
                </div>
              </section>

            </div>
          )}

        </div>

      </main>

        {/* Phone navigation. A flex sibling of the page, not a fixed overlay,
            so content is never trapped behind it — and outside <main>, so the
            landmark holds the page alone. */}
        <MobileTabBar />
      </div>

      {/* Missing API Key Modal */}
      <Modal
        isOpen={showKeyModal}
        onClose={() => setShowKeyModal(false)}
        eyebrow="Setup"
        title={!geminiOk && !uploadPostKey
          ? 'Two keys before your first clip'
          : !geminiOk
            ? 'Add your Gemini API key'
            : 'Add your Upload-Post API key'}
        footer={
          <div className="flex flex-col-reverse sm:flex-row gap-2 sm:gap-3">
            <button
              type="button"
              onClick={() => setShowKeyModal(false)}
              className="btn-ghost sm:flex-1 px-4 py-2 text-sm"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => { setShowKeyModal(false); goToTab('settings'); }}
              className="btn-accent sm:flex-1 px-4 py-2 text-sm"
            >
              Open Settings
            </button>
          </div>
        }
      >
        <div className="space-y-4">
          <p className="text-sm text-muted leading-relaxed">
            Synapse AI runs on a <strong className="font-medium text-ink2">Gemini</strong> key (finding the moments) and
            an <strong className="font-medium text-ink2">Upload-Post</strong> key (publishing). Both have free tiers.
            Paste a key and press Enter, or set them in Settings.
          </p>

          {/* Gemini */}
          <section aria-labelledby="key-modal-gemini-title" className={`tray p-4 space-y-3 ${apiKey ? 'opacity-70' : ''}`}>
            <div className="flex items-center justify-between gap-3">
              <h3 id="key-modal-gemini-title" className="text-sm font-medium text-ink">Gemini API key</h3>
              {apiKey
                ? <span className="badge-ok"><Check size={11} aria-hidden="true" /> Set</span>
                : <span className="badge-warn"><AlertTriangle size={11} aria-hidden="true" /> Missing</span>}
            </div>
            {!apiKey && (
              <>
                <ol className="text-xs text-muted space-y-1 list-decimal pl-4 leading-relaxed">
                  <li>Open <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noopener noreferrer" className="text-cobalt underline underline-offset-2 hover:text-ink">aistudio.google.com/app/apikey</a></li>
                  <li>Sign in with your Google account</li>
                  <li>Choose "Create API key"</li>
                  <li>Copy the key and paste it below</li>
                </ol>
                <label htmlFor="key-modal-gemini" className="sr-only">Gemini API key</label>
                <input
                  id="key-modal-gemini"
                  type="text"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="Paste your Gemini API key, then press Enter"
                  className="input-field font-mono"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && e.target.value.trim()) {
                      setApiKey(e.target.value.trim());
                    }
                  }}
                />
              </>
            )}
          </section>

          {/* Upload-Post */}
          <section aria-labelledby="key-modal-upload-post-title" className={`tray p-4 space-y-3 ${uploadPostKey ? 'opacity-70' : ''}`}>
            <div className="flex items-center justify-between gap-3">
              <h3 id="key-modal-upload-post-title" className="text-sm font-medium text-ink">Upload-Post API key</h3>
              {uploadPostKey
                ? <span className="badge-ok"><Check size={11} aria-hidden="true" /> Set</span>
                : <span className="badge-warn"><AlertTriangle size={11} aria-hidden="true" /> Missing</span>}
            </div>
            {!uploadPostKey && (
              <>
                <p className="text-xs text-muted leading-relaxed">
                  Publishes your clips to TikTok, Instagram Reels and YouTube Shorts. Free tier, no credit card needed.
                </p>
                <ol className="text-xs text-muted space-y-1 list-decimal pl-4 leading-relaxed">
                  <li>Register at <a href="https://app.upload-post.com/login" target="_blank" rel="noopener noreferrer" className="text-cobalt underline underline-offset-2 hover:text-ink">app.upload-post.com</a></li>
                  <li>Connect your TikTok, Instagram or YouTube accounts</li>
                  <li>Open <a href="https://app.upload-post.com/api-keys" target="_blank" rel="noopener noreferrer" className="text-cobalt underline underline-offset-2 hover:text-ink">API keys</a> and generate one</li>
                  <li>Paste it below</li>
                </ol>
                <label htmlFor="key-modal-upload-post" className="sr-only">Upload-Post API key</label>
                <input
                  id="key-modal-upload-post"
                  type="text"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="Paste your Upload-Post API key, then press Enter"
                  className="input-field font-mono"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && e.target.value.trim()) {
                      setUploadPostKey(e.target.value.trim());
                    }
                  }}
                />
              </>
            )}
          </section>
        </div>
      </Modal>

      <ScheduleWeekModal
        isOpen={showScheduleWeek}
        onClose={() => { setShowScheduleWeek(false); refreshResults(); }}
        project={scheduleProject}
        uploadPostKey={uploadPostKey}
        uploadUserId={uploadUserId}
        profiles={userProfiles}
        isManaged={isManaged}
        lastNiche={niche}
        onNicheChosen={(choice) => saveProjectNiche(choice.niche, choice.profile)}
        onOpenPlan={billingEnabled ? undefined : () => goToTab('publish-plan')}
      />

      {/* Asked before EVERY download (never silently reused) — picking a
          niche here also updates Settings' "Content Niche & Hashtags" field
          and the shared history every other niche picker reads from. */}
      <NichePromptModal
        isOpen={showNichePrompt}
        onClose={() => setShowNichePrompt(false)}
        defaultValue={proposedNiche}
        message="Real hashtags from top-performing Shorts in this niche will be added to each clip's bundled text file. Leave it blank to download without them."
        onSkip={() => { setShowNichePrompt(false); downloadAllWithNiche(''); }}
        onConfirm={(n) => {
          saveProjectNiche(n);
          setShowNichePrompt(false);
          downloadAllWithNiche(n);
        }}
      />

      {/* Pre-flight quality gate */}
      {qualityGate && (
        <Modal isOpen={true} onClose={() => setQualityGate(null)} size="md" eyebrow="Heads up" title="This source is below HD">
          <div className="space-y-4">
            {/* The numbers, read at a glance: what YouTube offers vs what we recommend. */}
            <dl className="grid grid-cols-2 gap-px rounded-card overflow-hidden border border-rule bg-paper3">
              <div className="bg-paper2 px-4 py-3">
                <dt className="readout">Available</dt>
                <dd className="font-quote text-3xl text-ink mt-1">{qualityGate.info.max_height}p</dd>
              </div>
              <div className="bg-paper2 px-4 py-3">
                <dt className="readout">Recommended</dt>
                <dd className="font-quote text-3xl text-muted mt-1">{qualityGate.info.min_height}p</dd>
              </div>
            </dl>
            <p className="text-sm text-ink2 leading-relaxed">
              YouTube only offers {qualityGate.info.max_height}p for this video. Processing anyway will produce lower-quality clips.
            </p>
            {qualityGate.info.cookies_invalid && (
              <p className="tray px-3.5 py-3 text-xs text-muted leading-relaxed">
                Your YouTube cookies look expired. Refreshing them (export again from an incognito window) often unlocks HD.
              </p>
            )}
            <div className="flex flex-col-reverse sm:flex-row gap-2 sm:justify-end pt-2">
              <button type="button" onClick={() => setQualityGate(null)} className="btn-ghost">Cancel</button>
              <button
                type="button"
                onClick={() => { const d = qualityGate.data; setQualityGate(null); handleProcess(d, true); }}
                className="btn-primary"
              >
                Process anyway
              </button>
            </div>
          </div>
        </Modal>
      )}


      {editingClip !== null && results?.clips?.[editingClip] && (
        <ClipEditor
          jobId={jobId}
          clipIndex={editingClip}
          clipTitle={results.clips[editingClip].video_title_for_youtube_short || ''}
          onClose={() => setEditingClip(null)}
          onRerendered={handleClipRerendered}
        />
      )}
      {reframingClip !== null && results?.clips?.[reframingClip] && (
        <ReframeEditor
          jobId={jobId}
          clipIndex={reframingClip}
          clipTitle={results.clips[reframingClip].video_title_for_youtube_short || ''}
          onClose={() => setReframingClip(null)}
          onReframed={handleClipRerendered}
        />
      )}
      {showLogin && <LoginModal onClose={() => setShowLogin(false)} />}
      {tutorialPhase && (
        <ClipTutorial
          phase={tutorialPhase}
          jobStatus={status}
          onStart={startTutorial}
          onSkip={skipTutorial}
          onDismissCelebrate={finishTutorial}
        />
      )}
      {showPlanChoice && <PlanChoiceModal onClose={() => setShowPlanChoice(false)} />}
      {showTopUp && (
        <TopUpModal
          onClose={() => setShowTopUp(false)}
          required={topUpInfo.required}
          remaining={topUpInfo.remaining}
          context={topUpInfo.context || 'wall'}
        />
      )}
      {showTrialUpgrade && (
        <TrialUpgradeModal
          plan={plan}
          onActivated={refreshMe}
          onClose={() => setShowTrialUpgrade(false)}
        />
      )}
    </div>
  );
}

export default App;
