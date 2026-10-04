import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Square, Upload, Sparkles, Youtube, Instagram, Share2, ChevronDown, Check, Activity, LayoutDashboard, Settings, Plus, History, X, Terminal, Shield, LayoutGrid, Image, Globe, RotateCcw, Calendar, AlertTriangle, KeyRound, Bot, Users, Smartphone, ExternalLink, Copy, CheckCircle2, Mail, Loader2, Download, Menu, Lock, Eraser, Hash, Flame, Clapperboard, Rocket, Library, Images } from 'lucide-react';
import KeyInput from './components/KeyInput';
import MediaInput from './components/MediaInput';
import McpConnectCard from './components/McpConnectCard';
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
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}>
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

const ProfileNetworkIcons = ({ profile, size = 12 }) => (
  <span className="flex items-center gap-1.5">
    <span className={profile?.connected?.includes('tiktok') ? 'text-ink' : 'text-muted opacity-40'}>
      <TikTokIcon size={size} />
    </span>
    <span className={profile?.connected?.includes('instagram') ? 'text-ink' : 'text-muted opacity-40'}>
      <Instagram size={size} />
    </span>
    <span className={profile?.connected?.includes('youtube') ? 'text-ink' : 'text-muted opacity-40'}>
      <Youtube size={size} />
    </span>
  </span>
);

const UserProfileSelector = ({ profiles, selectedUserId, onSelect, onConnect }) => {
  const [isOpen, setIsOpen] = useState(false);

  if (!profiles || profiles.length === 0) return null;

  const selectedProfile = profiles.find(p => p.username === selectedUserId) || profiles[0];
  const autoId = isAutoProfileId(selectedProfile?.username);

  return (
    <div className="relative z-50">
      <button
        onClick={() => setIsOpen(!isOpen)}
        aria-label="social profile"
        /* Phone: avatar + chevron only. A 180px pill next to the menu button,
           the section title and the minutes meter overflowed a 360px header. */
        className="flex items-center justify-between gap-1 bg-paper2 border border-rule2 rounded-input px-2 sm:px-3 py-2 text-sm text-ink2 hover:bg-paper3 transition-colors sm:min-w-[180px]"
      >
        <span className="flex items-center gap-2">
          <div className="w-5 h-5 rounded-full bg-paper3 border border-rule flex items-center justify-center font-mono text-micro text-brass shrink-0">
            {autoId ? "S" : (selectedProfile?.username?.substring(0, 1).toUpperCase() || "U")}
          </div>
          {autoId ? (
            <span className="hidden sm:flex"><ProfileNetworkIcons profile={selectedProfile} size={13} /></span>
          ) : (
            <span className="hidden sm:block font-medium text-ink truncate max-w-[100px]">{selectedProfile?.username || "Select User"}</span>
          )}
        </span>
        <ChevronDown size={14} className={`text-muted transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <div className="absolute top-full mt-2 right-0 w-64 card overflow-hidden">
          <div className="max-h-60 overflow-y-auto custom-scrollbar">
            {profiles.map((profile) => (
              <button
                key={profile.username}
                onClick={() => {
                  onSelect(profile.username);
                  setIsOpen(false);
                }}
                className="w-full flex items-center justify-between px-4 py-3 hover:bg-paper3 transition-colors text-left group border-b border-rule last:border-0"
              >
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-paper3 flex items-center justify-center font-mono text-micro text-ink border border-rule shrink-0">
                    {isAutoProfileId(profile.username) ? "S" : profile.username.substring(0, 2).toUpperCase()}
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-ink2 group-hover:text-ink transition-colors truncate">
                      {isAutoProfileId(profile.username)
                        ? `Social profile ${profiles.indexOf(profile) + 1}`
                        : profile.username}
                    </div>
                    <div className="flex gap-2 mt-0.5">
                      {/* Status indicators */}
                      <div className={`flex items-center gap-1 ${profile.connected.includes('tiktok') ? 'text-ink2' : 'text-muted opacity-40'}`}>
                        <TikTokIcon size={10} />
                      </div>
                      <div className={`flex items-center gap-1 ${profile.connected.includes('instagram') ? 'text-ink2' : 'text-muted opacity-40'}`}>
                        <Instagram size={10} />
                      </div>
                      <div className={`flex items-center gap-1 ${profile.connected.includes('youtube') ? 'text-ink2' : 'text-muted opacity-40'}`}>
                        <Youtube size={10} />
                      </div>
                    </div>
                  </div>
                </div>
                {selectedUserId === profile.username && <Check size={14} className="text-brass shrink-0" />}
              </button>
            ))}
          </div>
          {/* For managed users this dropdown otherwise does nothing (one profile,
              nothing to switch) — its real job is being the door to connecting
              the greyed-out networks it displays. */}
          {onConnect && (
            <button
              onClick={() => { setIsOpen(false); onConnect(); }}
              className="w-full flex items-center gap-2 px-4 py-3 text-sm text-brass hover:bg-paper3 transition-colors text-left border-t border-rule"
            >
              <Share2 size={14} /> Connect / manage accounts
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
  const [nicheTitleHashtags, setNicheTitleHashtags] = useState(null);
  const [nicheError, setNicheError] = useState('');
  const [nicheHistory, setNicheHistory] = useState(() => loadNicheHistory());
  // Server-side publish setting (publish_settings.json): 3-5 hashtags about
  // each clip + none in the YouTube title, instead of the niche's whole pool.
  const [cleanHashtags, setCleanHashtags] = useState(true);
  // YouTube's hidden tags field: the clip's topics + these base tags of the
  // niche, sent with every YouTube upload (Upload-Post tags[]).
  const [ytTags, setYtTags] = useState(true);
  const [nicheTagsTable, setNicheTagsTable] = useState({});
  const [nicheTagsDraft, setNicheTagsDraft] = useState('');
  const [nicheTagsSaved, setNicheTagsSaved] = useState(false);
  const applyPublishSettings = (d) => {
    setCleanHashtags(d.clean_hashtags !== false);
    setYtTags(d.youtube_tags !== false);
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
  const saveCleanHashtags = (value) => { setCleanHashtags(value); savePublishSettings({ clean_hashtags: value }); };
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
  // The Clip Generator++ profile picked in its tab (used by the results' "viral style").
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
  // Clip Generator++ is shown. The classic tab's code stays; every path that
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
  // Advanced (bring your own fal.ai + ElevenLabs keys): AI Shorts + AI Agent.
  const INCLUDED_TOOL_TABS = ['dashboard', 'thumbnails'];
  const ADVANCED_TOOL_TABS = ['saasshorts', 'ai-agent'];
  const TOOL_NAMES = { dashboard: 'the Clip Generator', thumbnails: 'the YouTube Studio' };
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
    ...(hideClassic ? [] : [{ id: 'dashboard', group: 'create', icon: LayoutDashboard, label: 'Clip Generator', short: 'clips', primary: true,
      desc: 'Paste a link or drop a video: the best moments, cut into vertical shorts.' }]),
    ...(!billingEnabled ? [{ id: 'plus', group: 'create', icon: Rocket, label: 'Clip Generator++', short: 'clips++', primary: hideClassic,
      desc: 'Your channel profiles: moments, hooks, captions and drawn B-roll, in your house style.' }] : []),
    { id: 'saasshorts', group: 'create', icon: Sparkles, label: 'AI Shorts', short: 'ai shorts', byok: true, primary: true,
      desc: 'Generate a short from a script or a product, voiced and edited by AI.' },
    { id: 'ai-agent', group: 'create', icon: Bot, label: 'AI Agent', short: 'agent', byok: true,
      desc: 'Talk to the studio: ask an agent to clip, write or publish for you.' },
    ...(!billingEnabled ? [{ id: 'story', group: 'create', icon: Clapperboard, label: 'Story Channel', short: 'story',
      desc: 'Long stories told as a series of shorts.' }] : []),
    ...(!billingEnabled || isSignedIn ? [{ id: 'history', group: 'library', icon: History, label: 'History', short: 'history',
      desc: 'Every project you made, ready to reopen.' }] : []),
    { id: 'ugc-gallery', group: 'library', icon: LayoutGrid, label: 'UGC Gallery', short: 'gallery', primary: true,
      desc: 'The videos generated with AI actors.' },
    ...(!billingEnabled ? [{ id: 'broll-gallery', group: 'library', icon: Images, label: 'B-roll images', short: 'images',
      desc: 'Every drawn picture, kept or refused: thumbs up or down, why, what to change.' }] : []),
    ...(!billingEnabled ? [{ id: 'notions', group: 'library', icon: Library, label: 'Notion pictures', short: 'notions',
      desc: 'The pictures kept for the notions of your episodes.' }] : []),
    { id: 'thumbnails', group: 'grow', icon: Image, label: 'YouTube Studio', short: 'studio', primary: true,
      desc: 'Thumbnails, titles and descriptions for YouTube.' },
    ...(!billingEnabled ? [{ id: 'viral-finder', group: 'grow', icon: Flame, label: 'Viral Finder', short: 'finder',
      desc: 'Find the videos that are taking off in your niche.' }] : []),
    { id: 'reworker', group: 'grow', icon: Eraser, label: 'Viral Clip Reworker', short: 'reworker', byok: true,
      desc: 'Take a viral clip and make it yours.' },
    ...(!billingEnabled ? [{ id: 'publish-plan', group: 'grow', icon: Calendar, label: 'Publish Plan', short: 'plan',
      desc: 'Plan and schedule your posts across platforms.' }] : []),
    { id: 'settings', group: 'system', icon: Settings, label: 'Settings', short: 'settings',
      desc: 'API keys, connected accounts and preferences.' },
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
        title={locked ? 'Finish your first clips to unlock' : `${item.label} — ${item.desc}`}
        className={`group relative w-full flex items-center gap-3 rounded-input transition-all min-h-[44px] ${drawer ? 'px-3 py-2' : 'px-2.5 py-1.5'}
          ${isActive ? 'bg-paper3/80 text-ink nav-glow' : 'text-ink2/75 hover:text-ink hover:bg-paper3/50'}
          ${locked ? 'opacity-40 cursor-not-allowed hover:bg-transparent' : ''}`}
      >
        <span className={`flex items-center justify-center w-8 h-8 rounded-lg shrink-0 transition-all
          ${isActive ? 'nav-tile-active' : 'bg-paper3/70 border border-rule group-hover:border-rule2'}`}>
          <NavIcon size={16} className={isActive ? 'text-brassink' : 'text-ink2'} aria-hidden="true" />
        </span>
        <span className={`text-[0.92rem] flex-1 text-left truncate ${compact ? 'hidden lg:block' : ''}`}>{item.label}</span>
        {locked
          ? <Lock size={12} className={`shrink-0 ${compact ? 'hidden lg:block' : ''}`} aria-label="locked" />
          : item.byok ? <span className={`chip-byok ${compact ? 'hidden lg:inline-flex' : ''}`} title="Bring your own keys (fal.ai, ElevenLabs)">BYOK</span> : null}
      </button>
    );
  };

  // The rail's and the drawer's sections: Create, Library, Grow; Settings pinned below.
  const NavSections = ({ compact = false, drawer = false }) => (
    <>
      {NAV_GROUPS.map((g) => {
        const items = navItems.filter((n) => n.group === g.id);
        if (!items.length) return null;
        return (
          <div key={g.id} className="space-y-0.5" role="group" aria-labelledby={`nav-group-${g.id}${drawer ? '-d' : ''}`}>
            <p id={`nav-group-${g.id}${drawer ? '-d' : ''}`}
              className={`nav-group-label px-3 pt-4 pb-1.5 ${compact ? 'hidden lg:block' : ''}`}>{g.label}</p>
            {compact && <div className="lg:hidden h-px mx-3 my-3 bg-rule" aria-hidden="true" />}
            {items.map((item) => <NavButton key={item.id} item={item} compact={compact} drawer={drawer} />)}
          </div>
        );
      })}
    </>
  );

  // Shared footer links — same list in the desktop rail and the mobile drawer, so they can never drift apart.
  const NavFooterLinks = ({ collapsed = false }) => (
    <>
      <a href="#landing" className="flex items-center gap-2 px-3 py-2 min-h-[36px] text-xs text-muted hover:text-ink2 transition-colors rounded-input">
        <Globe size={14} className="shrink-0" aria-hidden="true" />
        <span className={collapsed ? 'hidden lg:block truncate' : 'truncate'}>Synapse AI home</span>
      </a>
      <a
        href="https://github.com/mutonby/openshorts"
        target="_blank"
        rel="noopener noreferrer"
        className="flex items-center gap-2 px-3 py-2 min-h-[36px] text-xs text-muted hover:text-ink2 transition-colors rounded-input"
        title="Synapse AI is built on OpenShorts, open source under the MIT license"
      >
        <svg height="14" viewBox="0 0 16 16" version="1.1" width="14" aria-hidden="true" fill="currentColor" className="shrink-0"><path fillRule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"></path></svg>
        <span className={collapsed ? 'hidden lg:block truncate' : 'truncate'}>built on OpenShorts (MIT)</span>
      </a>
      {billingEnabled && (
        <a href="#/pricing" className="flex items-center gap-2 px-3 py-2 min-h-[36px] text-xs text-muted hover:text-ink2 transition-colors rounded-input">
          <Sparkles size={14} className="shrink-0" aria-hidden="true" />
          <span className={collapsed ? 'hidden lg:block truncate' : 'truncate'}>plans &amp; pricing</span>
        </a>
      )}
    </>
  );

  // The brand block, the same in the rail and the drawer.
  const Brand = ({ compact = false, onClick }) => (
    <a href="#landing" onClick={onClick} className="flex items-center gap-3 min-w-0" title="Synapse AI home">
      <img src="/logo-synapse.svg" alt="" className="w-9 h-9 shrink-0 rounded-[10px] logo-glow" />
      <span className={`flex flex-col leading-none ${compact ? 'hidden lg:flex' : ''}`}>
        <span className="brand-word text-[1.15rem]">synapse <span className="brand-ai">ai</span></span>
        <span className="readout mt-1">clip studio</span>
      </span>
    </a>
  );

  const NewClipButton = ({ compact = false }) => (
    <button
      type="button"
      onClick={() => goToTab(newClipTab)}
      className={`btn-primary w-full ${compact ? 'px-0 lg:px-4' : 'px-4'} py-2.5 text-sm`}
      aria-label="New clip"
    >
      <Plus size={16} aria-hidden="true" />
      <span className={compact ? 'hidden lg:inline' : ''}>new clip</span>
    </button>
  );

  // Desktop rail: icon-only from md, labelled from lg. Below md it is gone — a phone gets the drawer and the tab bar.
  const Sidebar = () => (
    <aside className="hidden md:flex w-[76px] lg:w-[272px] shell-rail flex-col h-full shrink-0 transition-all duration-300" aria-label="Main">
      <div className="px-4 lg:px-5 pt-5 pb-4 flex items-center justify-center lg:justify-start">
        <Brand compact />
      </div>
      <div className="px-3 lg:px-4 pb-2">
        <NewClipButton compact />
      </div>
      <nav className="flex-1 overflow-y-auto custom-scrollbar px-2.5 lg:px-3 pb-3" aria-label="Sections">
        <NavSections compact />
      </nav>
      <div className="px-2.5 lg:px-3 pt-2 pb-3 border-t border-rule space-y-0.5">
        {navItems.filter((n) => n.group === 'system').map((item) => <NavButton key={item.id} item={item} compact />)}
        <NavFooterLinks collapsed />
      </div>
    </aside>
  );

  // Mobile drawer: the complete nav, reachable from the header's menu button.
  const MobileNavDrawer = () => (
    <div className="md:hidden fixed inset-0 z-[90] flex" role="dialog" aria-modal="true" aria-label="Navigation">
      <div className="absolute inset-0 bg-black/70 animate-fade" onClick={() => setNavOpen(false)} aria-hidden="true" />
      <div className="relative w-[18rem] max-w-[86vw] h-full shell-rail flex flex-col animate-slide-in-left">
        <div className="flex items-center justify-between px-5 h-16 border-b border-rule shrink-0">
          <Brand onClick={() => setNavOpen(false)} />
          <button onClick={() => setNavOpen(false)} aria-label="Close navigation"
            className="p-2.5 -mr-2 rounded-input text-muted hover:text-ink transition-colors">
            <X size={20} />
          </button>
        </div>
        <div className="px-4 pt-4"><NewClipButton /></div>
        <nav className="flex-1 overflow-y-auto custom-scrollbar px-3 pb-3" aria-label="Sections">
          <NavSections drawer />
          <div className="pt-3 mt-3 border-t border-rule space-y-0.5">
            {navItems.filter((n) => n.group === 'system').map((item) => <NavButton key={item.id} item={item} drawer />)}
          </div>
        </nav>
        <div className="px-3 py-3 border-t border-rule space-y-0.5 safe-bottom shrink-0">
          <NavFooterLinks />
        </div>
      </div>
    </div>
  );

  // Bottom tab bar: the everyday destinations plus "more" for the rest. A flex sibling of the scrolling pane rather
  // than `fixed`, so nothing ever hides behind it and no pane needs compensating padding.
  const MobileTabBar = () => {
    const tabs = navItems.filter((n) => n.primary);
    const moreActive = !tabs.some((t) => t.id === activeTab);
    return (
      <nav className="md:hidden shrink-0 border-t border-rule bg-paper2/90 backdrop-blur-md safe-bottom" aria-label="Quick sections">
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
                className={`flex-1 min-w-0 flex flex-col items-center justify-center gap-1 py-2 min-h-[58px] transition-colors ${isActive ? 'text-ink' : 'text-muted active:text-ink2'} ${tabLocked(item.id) ? 'opacity-40 cursor-not-allowed' : ''}`}
              >
                <span className={`flex items-center justify-center w-9 h-7 rounded-full ${isActive ? 'nav-tile-active' : ''}`}>
                  <NavIcon size={18} className={isActive ? 'text-brassink' : ''} aria-hidden="true" />
                </span>
                <span className="text-[11px] leading-none truncate max-w-full px-0.5">{item.short}</span>
              </button>
            );
          })}
          <button
            type="button"
            onClick={() => setNavOpen(true)}
            aria-label="More sections"
            aria-expanded={navOpen}
            className={`flex-1 min-w-0 flex flex-col items-center justify-center gap-1 py-2 min-h-[58px] transition-colors ${moreActive ? 'text-ink' : 'text-muted active:text-ink2'}`}
          >
            <span className={`flex items-center justify-center w-9 h-7 rounded-full ${moreActive ? 'nav-tile-active' : ''}`}>
              <Menu size={18} className={moreActive ? 'text-brassink' : ''} aria-hidden="true" />
            </span>
            <span className="text-[11px] leading-none">more</span>
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

      <main className="flex-1 min-w-0 flex flex-col h-full overflow-hidden relative" aria-labelledby="page-title">
        <svg className="neural-field" aria-hidden="true" viewBox="0 0 1200 800" preserveAspectRatio="xMidYMid slice">
          <defs>
            <linearGradient id="nf" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="oklch(81% 0.14 212)" />
              <stop offset="1" stopColor="oklch(68% 0.22 300)" />
            </linearGradient>
          </defs>
          <g stroke="url(#nf)" fill="none" strokeWidth="1.2" strokeLinecap="round">
            <path d="M980 90 C 900 160, 860 240, 780 260 S 640 300, 600 380" />
            <path d="M980 90 C 1040 170, 1100 200, 1180 210" />
            <path d="M980 90 C 960 30, 1010 0, 1060 -20" />
            <path d="M600 380 C 560 460, 640 540, 700 600 S 760 720, 900 760" />
            <path d="M600 380 C 520 400, 430 380, 360 430" />
            <path d="M780 260 C 820 330, 900 360, 1000 380" />
          </g>
          <g fill="url(#nf)">
            <circle cx="980" cy="90" r="5" className="neural-node" />
            <circle cx="600" cy="380" r="4" className="neural-node neural-node-2" />
            <circle cx="780" cy="260" r="3" />
            <circle cx="1000" cy="380" r="2.5" />
            <circle cx="360" cy="430" r="2.5" />
            <circle cx="900" cy="760" r="3" />
          </g>
        </svg>

        {/* Top bar: where you are (section · page), what the page does, and the studio's status. */}
        <header className="shell-topbar h-16 flex items-center justify-between gap-3 px-3 sm:px-6 shrink-0 z-10">
          <div className="flex items-center gap-2 sm:gap-3 min-w-0">
            <button
              type="button"
              onClick={() => setNavOpen(true)}
              aria-label="Open navigation"
              className="md:hidden -ml-1 p-2.5 rounded-input text-ink2 active:bg-paper3 transition-colors shrink-0"
            >
              <Menu size={20} />
            </button>
            {activeNav && (
              <span className="hidden sm:flex items-center justify-center w-9 h-9 rounded-[10px] nav-tile-active shrink-0" aria-hidden="true">
                <activeNav.icon size={17} className="text-brassink" />
              </span>
            )}
            <div className="min-w-0">
              <p className="readout leading-none mb-1 hidden sm:block">{activeGroup ? activeGroup.label : 'Synapse AI'}</p>
              <h1 id="page-title" data-tutorial="nav-clips" className="text-ink font-semibold text-[1.02rem] sm:text-lg leading-tight truncate tracking-tight">
                {activeNav?.label || 'Synapse AI'}
              </h1>
              {activeNav?.desc && <p className="hidden lg:block text-xs text-muted truncate max-w-[52ch]">{activeNav.desc}</p>}
            </div>
            {status !== 'idle' && (
              <button onClick={handleReset} className="btn-quiet px-3 py-1.5 text-xs shrink-0 ml-1" aria-label="New project">
                <Plus size={14} />
                <span className="hidden sm:inline">new project</span>
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
              <button onClick={() => setShowPlanChoice(true)} className="btn-primary px-4 py-2 text-xs">
                Choose a plan
              </button>
            )}
            {billingEnabled && !isSignedIn && (
              <button onClick={() => setShowLogin(true)} className="btn-ghost px-4 py-2 text-xs">
                Sign in
              </button>
            )}
            {billingEnabled && isSignedIn && <ProfileMenu />}

            {keysMissing ? (
              <button
                onClick={() => (billingEnabled && !isSignedIn ? setShowLogin(true) : goToTab('settings'))}
                className="status-pill status-pill-warn hidden sm:inline-flex"
                title="Configure API keys or choose a plan"
              >
                <AlertTriangle size={13} aria-hidden="true" />
                <span className="hidden md:inline">
                  {!geminiOk && !uploadPostKey
                    ? 'Gemini & Upload-Post keys missing'
                    : !geminiOk
                      ? 'Gemini key missing'
                      : 'Upload-Post key missing'}
                </span>
                <span className="md:hidden">keys missing</span>
              </button>
            ) : (
              <span className="status-pill status-pill-ok hidden sm:inline-flex" title="Your API keys are set">
                <span className="status-dot" aria-hidden="true" /> ready
              </span>
            )}
          </div>
        </header>

        {/* Persistent Missing Keys Banner — visible on every screen */}
        {keysMissing && activeTab !== 'settings' && (
          <div className="mx-3 sm:mx-6 mt-3 px-3.5 sm:px-4 py-3 bg-paper2 border border-rule rounded-card flex flex-wrap items-center justify-between gap-2.5 sm:gap-4 shrink-0 animate-fade">
            <div className="flex items-start sm:items-center gap-2.5 sm:gap-3 text-sm text-ink2 min-w-0 flex-1">
              <KeyRound size={16} className="shrink-0 text-warn mt-0.5 sm:mt-0" />
              <div className="min-w-0">
                <span className="font-medium text-ink">Required API keys missing.</span>{' '}
                <span className="text-muted">
                  {!geminiOk && !uploadPostKey
                    ? 'Set your Gemini and Upload-Post API keys to use Synapse AI.'
                    : !geminiOk
                      ? 'Set your Gemini API key to use Synapse AI.'
                      : 'Set your Upload-Post API key to use Synapse AI.'}
                </span>
              </div>
            </div>
            <button
              onClick={() => goToTab('settings')}
              className="btn-quiet px-3 py-1.5 text-xs shrink-0 w-full sm:w-auto"
            >
              Go to Settings
            </button>
          </div>
        )}

        {/* Session Recovery Banner */}
        {sessionRecovered && (
          <div className="mx-3 sm:mx-6 mt-2 px-3.5 sm:px-4 py-3 bg-paper2 border border-rule rounded-card flex items-start justify-between gap-3 animate-fade shrink-0">
            <div className="flex items-start sm:items-center gap-2 text-sm text-ink2 flex-wrap min-w-0">
              <RotateCcw size={16} className="text-brass shrink-0 mt-0.5 sm:mt-0" />
              <span className="font-medium">Session recovered</span>
              <span className="text-muted text-xs">Your previous work has been restored.</span>
            </div>
            <button
              onClick={() => setSessionRecovered(false)}
              aria-label="dismiss"
              className="text-muted hover:text-ink transition-colors shrink-0 -m-1 p-1"
            >
              <X size={16} />
            </button>
          </div>
        )}

        {/* Included tools (Clip Generator, YouTube Studio): non-blocking trial prompt. */}
        {gateThisTab && <TrialGate toolName={TOOL_NAMES[activeTab] || 'this'} />}

        {/* Advanced tools (AI Shorts, AI Agent): BYOK fal.ai + ElevenLabs notice. */}
        {advancedThisTab && <AdvancedBanner needsPlan={needsPlan} onKeys={() => goToTab('settings')} />}

        {/* Main Workspace */}
        <div id="main-content" tabIndex={-1} className="flex-1 overflow-hidden relative z-[1] focus:outline-none">

          {/* View: Settings */}
          {activeTab === 'settings' && (
            <div className="h-full overflow-y-auto p-4 sm:p-8 max-w-2xl mx-auto animate-fade">
              <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 mb-8">
                <div>
                  <p className="eyebrow mb-1.5">07 · SETTINGS</p>
                  <h1 className="font-display lowercase text-2xl text-ink">Settings</h1>
                </div>
                <div className="flex items-center gap-2 text-xs text-muted mt-1">
                  <Shield size={12} className="text-ok shrink-0" /> Privacy: keys only live in your browser (sent to backend just to process)
                </div>
              </div>

              <div className="card p-4 sm:p-6 mb-6">
                <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
                  <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-input bg-paper3 flex items-center justify-center shrink-0">
                      <Hash size={16} className="text-brass" />
                    </div>
                    <h2 className="text-base font-medium text-ink lowercase">Content Niche &amp; Hashtags</h2>
                  </div>
                  <span className="readout">optional</span>
                </div>
                <p className="text-xs text-muted mb-4 leading-relaxed">
                  Tell it what your channel reposts (e.g. "Joe Rogan podcast clips") and "refresh" in a
                  clip's descriptions will research real hashtags from top-performing Shorts in that niche
                  (YouTube Data API) instead of guessing generic ones.
                </p>
                {results?.niche_guess && niche.trim() === results.niche_guess.trim() && (
                  <p className="text-xs text-brass mb-3 -mt-1">
                    Guessed from this video by AI — correct it if it's off, it'll be remembered either way.
                  </p>
                )}
                <div className="flex flex-col sm:flex-row gap-2">
                  <input
                    type="text"
                    value={niche}
                    onChange={(e) => setNiche(e.target.value)}
                    className="input-field"
                    placeholder="e.g. Joe Rogan podcast clips"
                  />
                  <button
                    onClick={async () => {
                      if (!niche.trim() || nicheResearching) return;
                      setNicheResearching(true);
                      setNicheHashtags(null);
                      setNicheTitleHashtags(null);
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
                    className="btn-quiet py-2 px-4 text-sm shrink-0"
                  >
                    {nicheResearching ? 'researching…' : 'research now'}
                  </button>
                  <button
                    onClick={async () => {
                      if (!niche.trim() || nicheResearching) return;
                      // The pool is already ranked by real frequency (most
                      // common in top Shorts first) — same source data as
                      // "research now", just re-fetched if it's not cached
                      // yet and narrowed to the 3 worth spending a YouTube
                      // title's tight character budget on.
                      setNicheResearching(true);
                      setNicheError('');
                      try {
                        let pool = nicheHashtags;
                        if (!pool) {
                          const data = await apiJson('/api/hashtags/research', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ niche }),
                          });
                          pool = data.hashtags || [];
                          setNicheHashtags(pool);
                        }
                        setNicheTitleHashtags(pool.slice(0, 3));
                        setNicheHistory(pushNicheHistory(niche));
                      } catch (e) {
                        setNicheError(e.detail || e.message || 'Research failed');
                      } finally {
                        setNicheResearching(false);
                      }
                    }}
                    disabled={!niche.trim() || nicheResearching}
                    className="btn-quiet py-2 px-4 text-sm shrink-0"
                    title="Show the 3 hashtags worth spending a YouTube title's tight character budget on"
                  >
                    title
                  </button>
                </div>
                {nicheHistory.filter((n) => n.toLowerCase() !== niche.trim().toLowerCase()).length > 0 && (
                  <div className="mt-3">
                    <p className="eyebrow mb-1.5">recent niches</p>
                    <div className="flex flex-wrap gap-1.5">
                      {nicheHistory
                        .filter((n) => n.toLowerCase() !== niche.trim().toLowerCase())
                        .map((n) => (
                          <button
                            key={n}
                            onClick={() => setNiche(n)}
                            className="readout bg-paper3 hover:bg-paper2 px-2 py-1 rounded-full text-ink2"
                          >
                            {n}
                          </button>
                        ))}
                    </div>
                  </div>
                )}
                {nicheError && <p className="text-danger text-xs mt-3">{nicheError}</p>}
                <label className="flex items-start gap-3 mt-4 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={cleanHashtags}
                    onChange={(e) => saveCleanHashtags(e.target.checked)}
                    className="mt-0.5 accent-brass"
                  />
                  <span className="text-xs leading-relaxed">
                    <span className="text-ink">clean hashtags (recommended)</span>
                    <span className="text-muted block">
                      Each post gets 3-5 hashtags about that clip — the niche's 1-2 main tags + the ones matching its
                      topic — and none in the YouTube title. Off: the whole researched pool goes in every description
                      and fills the title (the old behaviour; unrelated tags read as spam to YouTube).
                    </span>
                  </span>
                </label>
                <label className="flex items-start gap-3 mt-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={ytTags}
                    onChange={(e) => { setYtTags(e.target.checked); savePublishSettings({ youtube_tags: e.target.checked }); }}
                    className="mt-0.5 accent-brass"
                  />
                  <span className="text-xs leading-relaxed">
                    <span className="text-ink">send youtube tags</span>
                    <span className="text-muted block">
                      Fills YouTube's hidden tags field on every upload: the clip's own topics first, then the base tags
                      below, within YouTube's 500 characters. The video's language is set from its transcript too.
                    </span>
                  </span>
                </label>
                {ytTags && niche.trim() && (
                  <div className="mt-3 ml-7">
                    <p className="eyebrow mb-1.5">base youtube tags for “{niche.trim()}”</p>
                    <textarea
                      value={nicheTagsDraft}
                      onChange={(e) => { setNicheTagsDraft(e.target.value); setNicheTagsSaved(false); }}
                      rows={3}
                      className="input-field text-xs"
                      placeholder="podcast, podcast clips, joe rogan, jre, mental health, science…"
                    />
                    <div className="flex items-center gap-3 mt-1.5">
                      <button
                        onClick={async () => {
                          setNicheTagsSaved(await savePublishSettings({ niche: niche.trim(), niche_tags: nicheTagsDraft }));
                        }}
                        className="btn-quiet py-1.5 px-3 text-xs"
                      >
                        save tags
                      </button>
                      <span className="text-xs text-muted">
                        {nicheTagsSaved ? 'saved' : 'comma-separated · every video of this niche gets them'}
                      </span>
                    </div>
                  </div>
                )}
                {nicheTitleHashtags && (
                  <div className="mt-3">
                    <p className="eyebrow mb-1.5">best for a youtube title</p>
                    <div className="flex flex-wrap gap-1.5">
                      {nicheTitleHashtags.length === 0 && <p className="text-xs text-muted">No hashtags found for this niche.</p>}
                      {nicheTitleHashtags.map((h) => (
                        <span key={h} className="readout bg-paper3 px-2 py-0.5 rounded-full text-brass border border-brass/40">{h}</span>
                      ))}
                    </div>
                  </div>
                )}
                {nicheHashtags && (
                  <div className="mt-3">
                    {nicheTitleHashtags && <p className="eyebrow mb-1.5">full pool</p>}
                    <div className="flex flex-wrap gap-1.5">
                      {nicheHashtags.length === 0 && !nicheTitleHashtags && <p className="text-xs text-muted">No hashtags found for this niche.</p>}
                      {nicheHashtags.map((h) => (
                        <span key={h} className="readout bg-paper3 px-2 py-0.5 rounded-full">{h}</span>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Self-hosted installs have no account page, so the agent
                  how-to lives here; cloud users get it (with OAuth) in Account. */}
              {!billingEnabled && <div className="mb-6"><McpConnectCard cloud={false} /></div>}
              {isManaged ? (
                <div className="card p-6 mb-2">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 rounded-input bg-paper3 flex items-center justify-center shrink-0">
                        <Shield size={16} className="text-brass" />
                      </div>
                      <h2 className="text-base font-medium text-ink lowercase">Included in your plan</h2>
                    </div>
                    <span className="badge-ok">Managed</span>
                  </div>
                  <p className="text-xs text-muted mb-5 leading-relaxed">
                    Your plan includes the <strong>Clip Generator</strong> and <strong>YouTube Studio</strong>,
                    fully managed — no API keys required. AI Shorts &amp; dubbing use your own fal.ai / ElevenLabs
                    keys (below). Connect your social accounts to publish directly.
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <button onClick={handleConnectSocials} className="btn-primary py-2 px-4 text-sm">
                      <Share2 size={16} /> Connect social accounts
                    </button>
                    <button onClick={handleOpenCalendar} className="btn-quiet py-2 px-4 text-sm">
                      <Calendar size={16} /> Content calendar
                    </button>
                  </div>
                </div>
              ) : billingEnabled ? (
                <div className="card p-6 mb-2">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 rounded-input bg-paper3 flex items-center justify-center shrink-0">
                        <Sparkles size={16} className="text-brass" />
                      </div>
                      <h2 className="text-base font-medium text-ink lowercase">Choose your plan</h2>
                    </div>
                    <span className="badge-ok">Free plan available</span>
                  </div>
                  <p className="text-xs text-muted mb-5 leading-relaxed">
                    Generate shorts with zero setup — no API keys needed. Start free with 20 min/month, or go paid from $12/mo. Cancel anytime.
                  </p>
                  <button onClick={() => setShowPlanChoice(true)} className="btn-primary py-2 px-4 text-sm">
                    <Sparkles size={16} /> Choose a plan
                  </button>
                </div>
              ) : (
                <>
              <KeyInput onKeySet={setApiKey} savedKey={apiKey} />

              <div className="card p-4 sm:p-6 mt-8">
                <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
                  <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-input bg-paper3 flex items-center justify-center shrink-0">
                      <Share2 size={16} className="text-brass" />
                    </div>
                    <h2 className="text-base font-medium text-ink lowercase">Social Integration</h2>
                  </div>
                  <span className="badge-warn">Required</span>
                </div>
                <p className="text-xs text-muted mb-6 leading-relaxed">
                  Required to publish your clips to TikTok, Instagram Reels, and YouTube Shorts via <strong>Upload-Post</strong>.
                  Includes a <strong>free tier</strong> (no credit card required).
                </p>
                <div className="space-y-4">
                  <label className="block text-sm text-muted">Upload-Post API Key</label>
                  <div className="flex flex-col sm:flex-row gap-2">
                    <input
                      type="password"
                      value={uploadPostKey}
                      onChange={(e) => setUploadPostKey(e.target.value)}
                      className="input-field"
                      placeholder="ey..."
                    />
                    <button onClick={fetchUserProfiles} disabled={connectStatus === 'loading'} className="btn-quiet py-2 px-4 text-sm">
                      {connectStatus === 'loading' ? <Loader2 size={14} className="animate-spin" /> : 'Connect'}
                    </button>
                  </div>
                  {connectStatus && connectStatus !== 'loading' && (
                    <p className={`text-xs flex items-center gap-1.5 ${connectStatus.ok ? 'text-ok' : 'text-danger'}`}>
                      {connectStatus.ok ? <Check size={13} /> : <AlertTriangle size={13} />}
                      {connectStatus.msg}
                    </p>
                  )}
                  {userProfiles.length > 0 && (() => {
                    const active = userProfiles.find((p) => p.username === uploadUserId) || userProfiles[0];
                    const connected = active?.connected || [];
                    return (
                      <p className="text-xs text-muted">
                        Posting as <span className="text-ink2">{active?.username}</span>
                        {' · '}
                        {connected.length
                          ? <span className="text-ok">{connected.join(', ')} connected</span>
                          : <span className="text-warn">no social account connected on this profile</span>}
                      </p>
                    );
                  })()}
                  <div className="text-xs text-muted leading-relaxed">
                    Connect your Upload-Post account to enable one-click publishing.
                    <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-2">
                      <a href="https://app.upload-post.com/login" target="_blank" rel="noopener noreferrer" className="p-2 border border-rule rounded-input hover:bg-paper3 transition-colors flex flex-col gap-1">
                        <span className="text-ink2 font-medium">1. Login</span>
                        <span className="text-xs text-muted">Register account</span>
                      </a>
                      <a href="https://app.upload-post.com/manage-users" target="_blank" rel="noopener noreferrer" className="p-2 border border-rule rounded-input hover:bg-paper3 transition-colors flex flex-col gap-1">
                        <span className="text-ink2 font-medium">2. Profiles</span>
                        <span className="text-xs text-muted">Create & Connect</span>
                      </a>
                      <a href="https://app.upload-post.com/api-keys" target="_blank" rel="noopener noreferrer" className="p-2 border border-rule rounded-input hover:bg-paper3 transition-colors flex flex-col gap-1">
                        <span className="text-ink2 font-medium">3. API Key</span>
                        <span className="text-xs text-muted">Generate key</span>
                      </a>
                    </div>
                    <br />
                    <span className="text-muted">
                      Keys are only stored in your browser. They are sent to the backend only to process your request, never stored server-side.
                    </span>
                  </div>
                </div>
              </div>

                </>
              )}

              <div className="card p-4 sm:p-6 mt-8">
                <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
                  <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-input bg-paper3 flex items-center justify-center shrink-0">
                      <Globe size={16} className="text-brass" />
                    </div>
                    <h2 className="text-base font-medium text-ink lowercase">Video Translation</h2>
                  </div>
                  <span className="readout">BYOK</span>
                </div>
                <p className="text-xs text-muted mb-6 leading-relaxed">
                  For <strong>AI Shorts &amp; dubbing</strong> — bring your own key. Translate your clips to different
                  languages using <strong>ElevenLabs</strong> AI dubbing (billed by ElevenLabs). Not covered by your plan.
                </p>
                <div className="space-y-4">
                  <label className="block text-sm text-muted">ElevenLabs API Key</label>
                  <div className="flex flex-col sm:flex-row gap-2">
                    <input
                      type="password"
                      value={elevenLabsKey}
                      onChange={(e) => setElevenLabsKey(e.target.value)}
                      className="input-field"
                      placeholder="sk_..."
                    />
                    <button
                      onClick={() => {
                        if (elevenLabsKey) {
                          localStorage.setItem('elevenLabsKey_v1', encrypt(elevenLabsKey));
                          setElevenLabsSaved(true);
                          setTimeout(() => setElevenLabsSaved(false), 2000);
                        }
                      }}
                      className={elevenLabsSaved ? 'badge-ok px-4' : 'btn-quiet py-2 px-4 text-sm'}
                    >
                      {elevenLabsSaved ? <><Check size={12} /> saved</> : 'Save'}
                    </button>
                  </div>
                  <div className="text-xs text-muted leading-relaxed">
                    Get your API key from ElevenLabs to enable video translation.
                    <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-2">
                      <a href="https://elevenlabs.io/sign-up" target="_blank" rel="noopener noreferrer" className="p-2 border border-rule rounded-input hover:bg-paper3 transition-colors flex flex-col gap-1">
                        <span className="text-ink2 font-medium">1. Sign Up</span>
                        <span className="text-xs text-muted">Create account</span>
                      </a>
                      <a href="https://elevenlabs.io/app/settings/api-keys" target="_blank" rel="noopener noreferrer" className="p-2 border border-rule rounded-input hover:bg-paper3 transition-colors flex flex-col gap-1">
                        <span className="text-ink2 font-medium">2. API Key</span>
                        <span className="text-xs text-muted">Generate key</span>
                      </a>
                    </div>
                    <br />
                    <span className="text-muted">
                      Keys are only stored in your browser. They are sent to the backend only to process your request, never stored server-side.
                    </span>
                  </div>
                </div>
              </div>

              <div className="card p-4 sm:p-6 mt-8">
                <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
                  <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-input bg-paper3 flex items-center justify-center shrink-0">
                      <Sparkles size={16} className="text-brass" />
                    </div>
                    <h2 className="text-base font-medium text-ink lowercase">AI Shorts (UGC Videos)</h2>
                  </div>
                  <span className="readout">BYOK</span>
                </div>
                <p className="text-xs text-muted mb-6 leading-relaxed">
                  Generate UGC-style videos with AI actors for any product or business using <strong>fal.ai</strong>.
                  <strong> Not covered by your plan</strong> — bring your own fal.ai + ElevenLabs keys (billed by those
                  providers, ~$0.65-2 per video). Your plan still covers the AI script &amp; orchestration.
                </p>
                <div className="space-y-4">
                  <label className="block text-sm text-muted">fal.ai API Key</label>
                  <div className="flex flex-col sm:flex-row gap-2">
                    <input
                      type="password"
                      value={falKey}
                      onChange={(e) => setFalKey(e.target.value)}
                      className="input-field"
                      placeholder="fal_..."
                    />
                    <button
                      onClick={() => {
                        if (falKey) {
                          localStorage.setItem('falKey_v1', encrypt(falKey));
                          setFalSaved(true);
                          setTimeout(() => setFalSaved(false), 2000);
                        }
                      }}
                      className={falSaved ? 'badge-ok px-4' : 'btn-quiet py-2 px-4 text-sm'}
                    >
                      {falSaved ? <><Check size={12} /> saved</> : 'Save'}
                    </button>
                  </div>
                  <div className="text-xs text-muted leading-relaxed">
                    Get your API key from fal.ai to enable AI actor video generation.
                    <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-2">
                      <a href="https://fal.ai/dashboard/keys" target="_blank" rel="noopener noreferrer" className="p-2 border border-rule rounded-input hover:bg-paper3 transition-colors flex flex-col gap-1">
                        <span className="text-ink2 font-medium">1. Sign Up</span>
                        <span className="text-xs text-muted">Create fal.ai account</span>
                      </a>
                      <a href="https://fal.ai/dashboard/keys" target="_blank" rel="noopener noreferrer" className="p-2 border border-rule rounded-input hover:bg-paper3 transition-colors flex flex-col gap-1">
                        <span className="text-ink2 font-medium">2. API Key</span>
                        <span className="text-xs text-muted">Generate key</span>
                      </a>
                    </div>
                    <br />
                    <span className="text-muted">
                      Keys are only stored in your browser. Sent to backend only to process requests.
                    </span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* View: SaaS Shorts */}
          {activeTab === 'saasshorts' && (
            <SaaShortsTab geminiApiKey={apiKey} elevenLabsKey={elevenLabsKey} falKey={falKey} uploadPostKey={uploadPostKey} uploadUserId={uploadUserId} managed={isManaged} />
          )}

          {/* View: AI Agent */}
          {activeTab === 'ai-agent' && (
            <div className="h-full overflow-y-auto custom-scrollbar p-4 sm:p-6 md:p-10 animate-fade">
              <div className="max-w-4xl mx-auto space-y-8">

                {/* Header */}
                <div className="space-y-3">
                  <p className="eyebrow flex items-center gap-2">
                    <Bot size={12} /> 03 · AI AGENT · AUTONOMOUS SKILL
                  </p>
                  <h1 className="font-display lowercase text-3xl md:text-4xl text-ink">
                    Your Personal Clipping Team
                  </h1>
                  <p className="text-muted text-base md:text-lg leading-relaxed max-w-2xl">
                    Drop your videos in a folder and a team of AI clippers picks the viral moments, edits them, and queues them for your approval — like having a 24/7 short-form editing crew on autopilot.
                  </p>
                </div>

                {/* Mobile-format warning */}
                <div className="px-4 py-3 rounded-card border border-rule bg-paper2 flex items-start gap-3">
                  <Smartphone size={18} className="text-warn shrink-0 mt-0.5" />
                  <div className="text-sm text-ink2">
                    <p className="font-medium text-ink mb-1">Upload videos already in vertical (9:16) mobile format.</p>
                    <p className="text-muted leading-relaxed">
                      The agent does not reframe horizontal footage. Make sure every source video is shot or pre-cropped to mobile/portrait format before dropping it into the input folder.
                    </p>
                  </div>
                </div>

                {/* Workflow */}
                <div className="grid md:grid-cols-3 gap-4">
                  <div className="card p-5 space-y-2">
                    <div className="w-10 h-10 rounded-input bg-paper3 flex items-center justify-center">
                      <Upload size={18} className="text-brass" />
                    </div>
                    <h3 className="font-medium text-ink lowercase">1. Drop your videos</h3>
                    <p className="text-xs text-muted leading-relaxed">
                      Put your long-form vertical footage in the watched folder. The skill picks one video per run.
                    </p>
                  </div>

                  <div className="card p-5 space-y-2">
                    <div className="w-10 h-10 rounded-input bg-paper3 flex items-center justify-center">
                      <Users size={18} className="text-brass" />
                    </div>
                    <h3 className="font-medium text-ink lowercase">2. AI clippers work</h3>
                    <p className="text-xs text-muted leading-relaxed">
                      Whisper transcribes, Gemini 3 Flash spots viral beats, FFmpeg cuts each clip and adds a hook overlay.
                    </p>
                  </div>

                  <div className="card p-5 space-y-2">
                    <div className="w-10 h-10 rounded-input bg-paper3 flex items-center justify-center">
                      <CheckCircle2 size={18} className="text-brass" />
                    </div>
                    <h3 className="font-medium text-ink lowercase">3. You validate, it ships</h3>
                    <p className="text-xs text-muted leading-relaxed">
                      Approve the candidates you like and the skill auto-publishes them to TikTok, Reels and YouTube Shorts via Upload-Post.
                    </p>
                  </div>
                </div>

                {/* Repo CTA */}
                <div className="card p-6 md:p-8 space-y-5">
                  <div className="flex items-start justify-between gap-4 flex-wrap">
                    <div>
                      <h2 className="font-display lowercase text-xl text-ink mb-1">skill-autoshorts</h2>
                      <p className="text-sm text-muted">
                        The Claude Code skill that powers this workflow. Install it once and trigger it whenever you want a fresh batch of clips.
                      </p>
                    </div>
                    <a
                      href="https://github.com/mutonby/skill-autoshorts"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn-primary py-2 px-4 text-sm shrink-0"
                    >
                      View on GitHub <ExternalLink size={14} />
                    </a>
                  </div>

                  <div className="bg-paper border border-rule rounded-card p-4 font-mono text-xs text-ink2 flex items-center justify-between gap-3">
                    <span className="truncate">git clone https://github.com/mutonby/skill-autoshorts</span>
                    <button
                      onClick={() => navigator.clipboard.writeText('git clone https://github.com/mutonby/skill-autoshorts')}
                      className="text-muted hover:text-ink transition-colors shrink-0"
                      title="Copy"
                    >
                      <Copy size={14} />
                    </button>
                  </div>

                  <div className="grid sm:grid-cols-2 gap-3 text-sm">
                    <div className="flex items-start gap-2 text-ink2">
                      <Check size={16} className="text-brass shrink-0 mt-0.5" />
                      <span>Daily batch — picks one long video per run</span>
                    </div>
                    <div className="flex items-start gap-2 text-ink2">
                      <Check size={16} className="text-brass shrink-0 mt-0.5" />
                      <span>Whisper transcription with word-level timing</span>
                    </div>
                    <div className="flex items-start gap-2 text-ink2">
                      <Check size={16} className="text-brass shrink-0 mt-0.5" />
                      <span>Gemini 3 Flash multimodal moment detection</span>
                    </div>
                    <div className="flex items-start gap-2 text-ink2">
                      <Check size={16} className="text-brass shrink-0 mt-0.5" />
                      <span>Auto-publish to TikTok, Reels & YouTube Shorts</span>
                    </div>
                  </div>
                </div>

              </div>
            </div>
          )}

          {/* View: UGC Gallery */}
          {activeTab === 'ugc-gallery' && (
            <div className="h-full overflow-y-auto custom-scrollbar animate-fade">
              <div className="max-w-6xl mx-auto p-4 sm:p-6 md:p-8">
                <UGCGallery />
              </div>
            </div>
          )}

          {/* View: History */}
          {activeTab === 'history' && (
            <div className="h-full overflow-y-auto custom-scrollbar animate-fade">
              <div className="max-w-6xl mx-auto p-4 sm:p-6 md:p-8">
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

          {activeTab === 'notions' && !billingEnabled && (
            <div className="h-full overflow-y-auto custom-scrollbar">
              <NotionLibrary />
            </div>
          )}

          {activeTab === 'broll-gallery' && !billingEnabled && (
            <div className="h-full overflow-y-auto custom-scrollbar">
              <BrollGallery />
            </div>
          )}

          {activeTab === 'publish-plan' && (
            <div className="h-full overflow-y-auto custom-scrollbar animate-fade">
              <div className="max-w-6xl mx-auto p-4 sm:p-6 md:p-8">
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

          {activeTab === 'story' && (
            <div className="h-full overflow-y-auto custom-scrollbar">
              <StoryTab geminiApiKey={apiKey} onOpenProject={restoreProject} />
            </div>
          )}

          {activeTab === 'viral-finder' && (
            <div className="h-full overflow-y-auto custom-scrollbar animate-fade">
              <div className="max-w-6xl mx-auto p-4 sm:p-6 md:p-8">
                <ViralFinderTab />
              </div>
            </div>
          )}

          {activeTab === 'thumbnails' && (
            <ThumbnailStudio
              geminiApiKey={apiKey}
              uploadPostKey={uploadPostKey}
              uploadUserId={uploadUserId}
              managed={isManaged}
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
              <div className="min-h-full flex flex-col items-center justify-center px-4 py-5 sm:p-6">
              {/* On a phone the hero used to fill the fold on its own and push
                  the uploader — the whole point of the screen — below it. The
                  eyebrow, the display size and the gaps all shrink first. */}
              <div className="max-w-xl w-full text-center space-y-5 sm:space-y-8">
                <div className="space-y-2.5 sm:space-y-4">
                  <p className="eyebrow hidden sm:block">01 · CLIP GENERATOR</p>
                  <h1 className="font-display lowercase text-3xl sm:text-4xl md:text-5xl text-ink">
                    Create Viral Shorts
                  </h1>
                  <p className="text-muted text-[15px] sm:text-lg leading-snug sm:leading-normal max-w-sm sm:max-w-none mx-auto">
                    Drop your long-form video below to instantly generate viral clips with AI.
                  </p>
                  {/* The same pipeline is an MCP server: point people at the
                      one place that explains how to drive it from an agent. */}
                  {!tutorialLock && (
                  <p className="text-xs text-muted">
                    Or let an agent do it:{' '}
                    <a
                      href={billingEnabled ? '#/account' : '#app'}
                      onClick={(e) => { if (!billingEnabled) { e.preventDefault(); goToTab('settings'); } }}
                      className="text-ink2 underline underline-offset-2 hover:text-brass transition-colors"
                    >
                      connect Claude, ChatGPT or n8n →
                    </a>
                  </p>
                  )}
                </div>

                <MediaInput
                  onProcess={handleProcess}
                  isProcessing={status === 'processing'}
                  publishProfiles={userProfiles}
                  defaultProfile={uploadUserId}
                  canAutoPublish={!billingEnabled && !!uploadPostKey && !!(uploadUserId || userProfiles.length)}
                />

                <div className="flex flex-wrap items-center justify-center gap-4 sm:gap-8 text-muted text-xs sm:text-sm">
                  <span className="flex items-center gap-2"><Youtube size={16} /> YouTube</span>
                  <span className="flex items-center gap-2"><Instagram size={16} /> Instagram</span>
                  <span className="flex items-center gap-2"><TikTokIcon size={16} /> TikTok</span>
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
            <div className="h-full flex flex-col md:flex-row gap-3 md:gap-4 p-3 md:p-4 overflow-y-auto md:overflow-y-hidden custom-scrollbar animate-fade">

              {/* Left Panel: Preview & Status */}
              <div className={`${status === 'complete' ? 'w-full md:w-[30%] lg:w-[25%]' : 'w-full md:w-[55%] lg:w-[60%]'} ${jobPanelFolded ? 'hidden' : ''} md:h-full flex flex-col shrink-0 md:shrink card p-3.5 sm:p-6 md:overflow-y-auto custom-scrollbar transition-all duration-700 ease-in-out`}>
                <div className="mb-4 sm:mb-6 flex items-center justify-between gap-2">
                  <h2 className="text-sm font-medium text-ink lowercase flex items-center gap-2">
                    <Activity className={`text-brass ${status === 'processing' ? 'animate-pulse' : ''}`} size={18} />
                    Live Analysis
                  </h2>
                  <div className="flex items-center gap-2">
                    {status === 'processing' && jobId && (
                      <button type="button" onClick={handleStopWork} disabled={stopping}
                        className="btn-quiet px-2.5 py-1 text-xs inline-flex items-center gap-1.5 text-red-400"
                        title="Stops the job now (transcription, analysis, rendering). Clips already finished stay.">
                        <Square size={12} />
                        {stopping ? 'stopping…' : 'stop work'}
                      </button>
                    )}
                    <span className={status === 'processing' ? 'badge-brass' :
                      status === 'complete' ? 'badge-ok' :
                        'badge-danger'
                      }>
                      {status.toUpperCase()}
                    </span>
                  </div>
                </div>

                {status === 'processing' && <JobProgressBar progress={jobProgress} />}

                {/* Who is thinking right now (ai_brain.py: Claude first, Gemini as fallback). */}
                {status === 'processing' && <BrainBadge logs={logs} />}

                {/* Video Preview */}
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

                {/* Phones only. The scan box drops its invented telemetry at
                    this size and the log terminal below starts collapsed, so
                    without this the screen would say nothing about what the job
                    is actually doing. The log tail is the real answer. */}
                {status === 'processing' && (
                  <div className="sm:hidden mb-3 flex items-start gap-2 text-xs text-ink2 min-w-0">
                    <Loader2 size={14} className="animate-spin text-brass shrink-0 mt-px" />
                    <span className="min-w-0 leading-snug break-words">
                      {logs.length ? (logs.filter(isKeyLog).slice(-1)[0] || logs[logs.length - 1]) : 'starting up…'}
                    </span>
                  </div>
                )}

                {/* The render is dead time: the user is watching a progress bar
                    with nothing to do, so this is where the one star ask goes. */}
                {status === 'processing' && (
                  <div className="my-3">
                    <StarBanner message="Got a minute while this renders?" />
                  </div>
                )}

                {/* Logs Terminal */}
                <div className={`bg-paper rounded-card border border-rule overflow-hidden flex flex-col transition-all duration-500 ${status === 'complete' ? `min-h-0 opacity-50 hover:opacity-100 ${logsVisible ? 'h-32' : 'h-auto'}` : `flex-1 ${logsVisible ? 'min-h-[160px] sm:min-h-[200px]' : 'min-h-0 flex-none'}`}`}>
                  <button
                    type="button"
                    onClick={() => setLogsVisible(!logsVisible)}
                    aria-expanded={logsVisible}
                    className="w-full px-3.5 sm:px-4 py-2.5 border-b border-rule flex items-center justify-between gap-2 bg-paper2 shrink-0 text-left"
                  >
                    <span className="readout flex items-center gap-2">
                      <Terminal size={12} /> System Logs
                    </span>
                    <span className="flex items-center gap-2 text-muted">
                      {!logsVisible && logs.length > 0 && (
                        <span className="readout normal-case">{logs.filter(isKeyLog).length}</span>
                      )}
                      <ChevronDown size={16} className={logsVisible ? '' : 'rotate-180'} />
                    </span>
                  </button>
                  {logsVisible && (
                    <div className="flex-1 p-3.5 sm:p-4 overflow-y-auto font-mono text-[11px] sm:text-xs space-y-1.5 custom-scrollbar text-muted break-words">
                      <div className="flex items-center gap-1.5 pb-1 font-sans">
                        {[['key', 'key info'], ['all', 'all logs']].map(([v, label]) => (
                          <button key={v} type="button" onClick={() => setLogMode(v)}
                            className={`readout px-2.5 py-0.5 rounded-full transition-colors ${logMode === v ? 'bg-paper3 text-ink' : 'text-muted hover:text-ink'}`}>
                            {label}
                          </button>
                        ))}
                        <span className="readout normal-case text-muted opacity-60">
                          {logMode === 'key' ? `${logs.filter(isKeyLog).length} of ${logs.length}` : logs.length}
                        </span>
                      </div>
                      {(logMode === 'key' ? logs.filter(isKeyLog) : logs).map((log, i) => (
                        <div key={i} className={`flex gap-2 ${log.toLowerCase().includes('error') ? 'text-danger' : 'text-muted'}`}>
                          <span className="text-muted opacity-50 shrink-0 hidden sm:inline">{new Date().toLocaleTimeString()}</span>
                          <span className="min-w-0 break-words">{log}</span>
                        </div>
                      ))}
                      {status === 'processing' && (
                        <div className="animate-pulse text-brass">_</div>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {/* Right Panel: Results Grid */}
              <div className={`${jobPanelFolded ? 'w-full' : status === 'complete' ? 'w-full md:w-[70%] lg:w-[75%]' : 'w-full md:w-[45%] lg:w-[40%]'} md:h-full flex flex-col shrink-0 md:shrink card p-3.5 sm:p-6 transition-all duration-700 ease-in-out`}>
                {/* Title + counters on one row, the two actions on their own row
                    below. Wrapping them all together dropped a lone half-width
                    "schedule week" pill under the title on a phone. */}
                <div className="mb-4 sm:mb-6 shrink-0 space-y-3">
                  <h2 className="font-display lowercase text-lg sm:text-xl text-ink flex flex-wrap items-center gap-2">
                    <span className="mr-auto">Generated Shorts</span>
                    {results?.clips?.length > 0 && (
                      <span className="readout bg-paper3 px-2.5 py-1 rounded-full">
                        {results.clips.length - postedCount} to post
                      </span>
                    )}
                    {postedCount > 0 && (
                      <button
                        onClick={() => setShowPosted((v) => !v)}
                        className={`readout px-2.5 py-1 rounded-full border transition-colors ${showPosted
                          ? 'bg-ok/15 border-ok/50 text-ok'
                          : 'bg-paper3 border-transparent hover:border-rule2'}`}
                        title="Posted clips leave the project so they can't be posted twice"
                      >
                        {postedCount} posted · {showPosted ? 'hide' : 'show'}
                      </button>
                    )}
                    {results?.cost_analysis && !isManaged && (
                      <span className="readout bg-paper3 px-2.5 py-1 rounded-full" title={`Input: ${results.cost_analysis.input_tokens} | Output: ${results.cost_analysis.output_tokens}`}>
                        GEMINI · ${results.cost_analysis.total_cost.toFixed(5)}
                      </span>
                    )}
                    {status === 'complete' && !processingMedia && (
                      <button
                        onClick={() => setShowJobPanel((v) => !v)}
                        className={`readout px-2.5 py-1 rounded-full border inline-flex items-center gap-1.5 transition-colors ${showJobPanel
                          ? 'bg-brass/15 border-brass/50 text-brass'
                          : 'bg-paper3 border-transparent hover:border-rule2'}`}
                        title="Show the job's logs"
                      >
                        <Terminal size={11} /> logs
                      </button>
                    )}
                  </h2>
                  {results?.clips?.length > 0 && status === 'complete' && (
                    <div className="flex flex-col sm:flex-row sm:justify-end items-stretch sm:items-center gap-2">
                      <button
                        onClick={handleDownloadAll}
                        disabled={downloadingAll}
                        className="btn-ghost px-3 py-2 text-xs"
                        title="Download all clips as a ZIP"
                      >
                        {downloadingAll
                          ? <><Loader2 size={14} className="animate-spin" />zipping…</>
                          : <><Download size={14} />download all</>}
                      </button>
                      <button
                        onClick={() => setShowScheduleWeek(true)}
                        className="btn-primary px-4 py-2 text-xs"
                      >
                        <Calendar size={14} />
                        schedule clips
                      </button>
                    </div>
                  )}
                </div>

                {status === 'complete' && results?.clips?.length > 0 && (
                  <div className="mb-2 space-y-2">
                    {/* Peak-moment upsell: they just SAW their clips — sell while
                        they're proud of the result, before asking for stars. */}
                    {plan === 'free' && (
                      <button
                        onClick={() => { setTopUpInfo({ context: 'upsell' }); setShowTopUp(true); }}
                        className="w-full text-left px-3 py-2.5 rounded-input bg-paper3 border border-brass/40 hover:border-brass text-sm transition-colors"
                      >
                        <span className="text-ink">Like these clips?</span>{' '}
                        <span className="text-muted">They carry a watermark and delete in 7 days.</span>{' '}
                        <span className="text-brass font-medium">Keep them forever →</span>
                      </button>
                    )}
                    {/* Distribution nudge at the same peak: clips on screen,
                        publishing them is one connect away. Hidden once any
                        network is linked or the user dismisses it. */}
                    {showSocialNudge && (
                      <div className="w-full flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 px-3 py-2.5 rounded-input bg-paper3 border border-rule text-sm">
                        <div className="flex items-start gap-3 flex-1 min-w-0">
                          <div className="min-w-0 leading-relaxed">
                            <span className="text-ink">Publish these clips straight from here.</span>{' '}
                            <span className="text-muted">Connect your YouTube, TikTok or Instagram once — after that every clip is one click from posted.</span>
                          </div>
                          {/* On a phone the dismiss X rides the copy, so the CTA
                              below can run the full width of the card. */}
                          <button
                            onClick={() => {
                              track('SocialNudgeDismissed');
                              setSocialNudgeDismissed(true);
                              try { localStorage.setItem('os_social_nudge_dismissed', '1'); } catch (_) { /* ignore */ }
                            }}
                            aria-label="dismiss"
                            className="sm:hidden shrink-0 -m-1 p-1 text-muted hover:text-ink"
                          >
                            <X size={16} />
                          </button>
                        </div>
                        <button
                          onClick={() => { track('SocialNudgeConnect'); handleConnectSocials(); }}
                          className="btn-quiet shrink-0 text-xs py-1.5 px-3 lowercase w-full sm:w-auto"
                        >
                          connect socials →
                        </button>
                        <button
                          onClick={() => {
                            track('SocialNudgeDismissed');
                            setSocialNudgeDismissed(true);
                            try { localStorage.setItem('os_social_nudge_dismissed', '1'); } catch (_) { /* ignore */ }
                          }}
                          aria-label="dismiss"
                          className="hidden sm:block shrink-0 p-1 text-muted hover:text-ink"
                        >
                          <X size={14} />
                        </button>
                      </div>
                    )}
                    {/* Self-host only: cloud archives clips to the video library,
                        here they really are gone once the retention sweep runs. */}
                    {!billingEnabled && jobRetentionSeconds > 0 && (
                      <div className="px-3 py-2.5 rounded-input bg-paper3 border border-paper3 text-sm">
                        <span className="text-ink">Clips are kept for {formatRetention(jobRetentionSeconds)}, then deleted.</span>{' '}
                        <span className="text-muted">Download what you want to keep, or raise JOB_RETENTION_SECONDS in your env.</span>
                      </div>
                    )}
                  </div>
                )}

                <div className="flex-1 overflow-y-auto custom-scrollbar p-1">
                  {results && results.clips && results.clips.length > 0 ? (
                    <div className={`grid gap-4 pb-10 ${status !== 'complete' ? 'grid-cols-1'
                      : jobPanelFolded ? 'grid-cols-1 lg:grid-cols-2 min-[1800px]:grid-cols-3' : 'grid-cols-1 xl:grid-cols-2'}`}>
                      {visibleClips.length === 0 && (
                        <div className="col-span-full text-center py-16 text-muted">
                          <p className="text-sm lowercase">Every clip of this project is posted. Nothing left to publish.</p>
                        </div>
                      )}
                      {visibleClips.map(({ clip, index: i }) => (
                        <div key={`${jobId}-${i}-${clip.video_url || ''}`} className={clip.published ? 'relative' : undefined}>
                          {clip.published && (
                            <div className="flex items-center justify-between gap-2 mb-1.5 px-3 py-1.5 rounded-input bg-ok/10 border border-ok/30 text-xs">
                              <span className="text-ok lowercase">
                                {clip.published.via === 'manual' ? 'posted by hand' : clip.published.scheduled_for ? `scheduled · ${clip.published.scheduled_for.slice(0, 16).replace('T', ' ')}` : 'posted'}
                              </span>
                              <button onClick={() => restoreClip(i)} className="text-muted hover:text-ink lowercase">
                                put back in project
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
                        </div>
                      ))}
                    </div>
                  ) : (
                    status === 'processing' ? (
                      <div className="h-full min-h-[140px] flex flex-col items-center justify-center text-muted space-y-3 text-center px-4">
                        <Loader2 size={28} className="animate-spin text-brass" />
                        <p className="text-sm lowercase">Waiting for clips...</p>
                        <p className="text-xs text-muted/80 max-w-[26ch] leading-snug">
                          They appear here one by one as each finishes rendering.
                        </p>
                      </div>
                    ) : status === 'error' ? (
                      <div className="h-full min-h-[120px] flex flex-col items-center justify-center text-danger space-y-2">
                        <p>Generation failed.</p>
                      </div>
                    ) : null
                  )}
                </div>
              </div>

            </div>
          )}

        </div>

        {/* Phone navigation. A flex sibling of the scrolling pane, not a fixed
            overlay, so content is never trapped behind it. */}
        <MobileTabBar />

      </main>

      {/* Missing API Key Modal */}
      <Modal
        isOpen={showKeyModal}
        onClose={() => setShowKeyModal(false)}
        eyebrow="SETUP"
        title={!geminiOk && !uploadPostKey
          ? 'Required API Keys Missing'
          : !geminiOk
            ? 'Gemini API Key Required'
            : 'Upload-Post API Key Required'}
        footer={
          <div className="flex gap-3">
            <button
              onClick={() => setShowKeyModal(false)}
              className="btn-ghost flex-1 px-4 py-2 text-sm"
            >
              Cancel
            </button>
            <button
              onClick={() => { setShowKeyModal(false); goToTab('settings'); }}
              className="btn-primary flex-1 px-4 py-2 text-sm"
            >
              Go to Settings
            </button>
          </div>
        }
      >
        <div className="space-y-4">
          <p className="text-sm text-muted">
            Synapse AI needs both a <strong className="text-ink2">Gemini</strong> API key and an <strong className="text-ink2">Upload-Post</strong> API key. Both have free tiers.
          </p>

          {/* Gemini block */}
          <div className={`rounded-input p-4 space-y-2 border ${!apiKey ? 'border-rule2' : 'border-rule opacity-70'}`}>
            <p className="text-xs font-medium text-ink flex items-center gap-2">
              {apiKey ? <Check size={12} className="text-ok" /> : <AlertTriangle size={12} className="text-warn" />}
              Gemini API Key {apiKey && <span className="text-ok">— set</span>}
            </p>
            {!apiKey && (
              <>
                <ol className="text-xs text-muted space-y-1 list-decimal list-inside">
                  <li>Go to <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noopener noreferrer" className="text-brass underline">aistudio.google.com/app/apikey</a></li>
                  <li>Sign in with your Google account</li>
                  <li>Click "Create API Key"</li>
                  <li>Copy the key and paste it below</li>
                </ol>
                <input
                  type="text"
                  placeholder="Paste your Gemini API key here..."
                  className="input-field"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && e.target.value.trim()) {
                      setApiKey(e.target.value.trim());
                    }
                  }}
                />
              </>
            )}
          </div>

          {/* Upload-Post block */}
          <div className={`rounded-input p-4 space-y-2 border ${!uploadPostKey ? 'border-rule2' : 'border-rule opacity-70'}`}>
            <p className="text-xs font-medium text-ink flex items-center gap-2">
              {uploadPostKey ? <Check size={12} className="text-ok" /> : <AlertTriangle size={12} className="text-warn" />}
              Upload-Post API Key {uploadPostKey && <span className="text-ok">— set</span>}
            </p>
            {!uploadPostKey && (
              <>
                <p className="text-xs text-muted">
                  Required to publish your clips to TikTok, Instagram Reels, and YouTube Shorts. Free tier available, no credit card needed.
                </p>
                <ol className="text-xs text-muted space-y-1 list-decimal list-inside">
                  <li>Register at <a href="https://app.upload-post.com/login" target="_blank" rel="noopener noreferrer" className="text-brass underline">app.upload-post.com</a></li>
                  <li>Connect your TikTok, Instagram, or YouTube accounts</li>
                  <li>Go to <a href="https://app.upload-post.com/api-keys" target="_blank" rel="noopener noreferrer" className="text-brass underline">API Keys</a> and generate one</li>
                  <li>Paste it below</li>
                </ol>
                <input
                  type="text"
                  placeholder="Paste your Upload-Post API key here..."
                  className="input-field"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && e.target.value.trim()) {
                      setUploadPostKey(e.target.value.trim());
                    }
                  }}
                />
              </>
            )}
          </div>
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
        <Modal isOpen={true} onClose={() => setQualityGate(null)} size="md" eyebrow="HEADS UP" title="low source quality">
          <div className="space-y-4">
            <p className="text-sm text-ink2">
              YouTube only offers <span className="text-brass font-semibold">{qualityGate.info.max_height}p</span> for this video
              (below the {qualityGate.info.min_height}p we recommend). Processing anyway will produce lower-quality clips.
            </p>
            {qualityGate.info.cookies_invalid && (
              <p className="text-xs text-muted">
                Your YouTube cookies look expired — refreshing them (export again from an incognito window) often unlocks HD.
              </p>
            )}
            <div className="flex gap-2 justify-end pt-2">
              <button onClick={() => setQualityGate(null)} className="btn-ghost">cancel</button>
              <button
                onClick={() => { const d = qualityGate.data; setQualityGate(null); handleProcess(d, true); }}
                className="btn-primary"
              >
                process anyway
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
