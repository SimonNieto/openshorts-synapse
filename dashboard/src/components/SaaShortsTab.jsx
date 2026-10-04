import { useState, useEffect } from 'react';
import { Globe, Download, Copy, Check, ChevronRight, ChevronLeft, Loader2, AlertCircle, Volume2, User, Film, Terminal, ChevronDown, RefreshCw, Share2, Calendar, Upload } from 'lucide-react';
import { getApiUrl } from '../config';
import { apiFetch } from '../lib/api';
import StepIndicator from './ui/StepIndicator';
import SegmentedControl from './ui/SegmentedControl';
import StarBanner from './StarBanner';

const STYLE_OPTIONS = [
  { id: 'ugc', label: 'UGC natural', desc: 'Authentic, talking to camera' },
  { id: 'educational', label: 'Educational', desc: 'Clear explanations' },
  { id: 'shock', label: 'Shock / discovery', desc: 'Surprising opener' },
  { id: 'story', label: 'Storytelling', desc: 'Mini narrative arc' },
  { id: 'comparison', label: 'Before / after', desc: 'Comparison style' },
];

const STEPS = ['Brief', 'Script', 'Cast', 'Generate', 'Result'];

const CACHE_KEY = 'saasshorts_cache';
const CACHE_MAX_AGE = 24 * 60 * 60 * 1000; // 24 hours

function loadCache() {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const cache = JSON.parse(raw);
    if (Date.now() - cache.timestamp > CACHE_MAX_AGE) {
      localStorage.removeItem(CACHE_KEY);
      return null;
    }
    return cache;
  } catch { return null; }
}

function saveCache(url, analysis, webResearch, scripts) {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify({
      url, analysis, webResearch, scripts, timestamp: Date.now(),
    }));
  } catch { /* localStorage full */ }
}

export default function SaaShortsTab({ geminiApiKey, elevenLabsKey, falKey, uploadPostKey, uploadUserId, managed = false }) {
  // Managed (hosted plan): Gemini (script) + Upload-Post run server-side via the
  // bearer token — no BYOK Gemini key needed. fal.ai + ElevenLabs stay BYOK.
  const geminiHeader = geminiApiKey ? { 'X-Gemini-Key': geminiApiKey } : {};
  const needsGeminiKey = !geminiApiKey && !managed;
  // Wizard state
  const [step, setStep] = useState(() => {
    const cache = loadCache();
    return cache ? 1 : 0;
  });

  // Step 0: URL input
  const [url, setUrl] = useState(() => loadCache()?.url || '');
  const [videoMode, setVideoMode] = useState('lowcost'); // "lowcost" or "premium"
  const [description, setDescription] = useState('');
  const [style, setStyle] = useState('ugc');
  const [language, setLanguage] = useState('en');
  const [actorGender, setActorGender] = useState('female');
  const [numScripts, setNumScripts] = useState(3);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState('');
  const [fromCache, setFromCache] = useState(() => !!loadCache());

  // Step 1: Analysis results
  const [analysis, setAnalysis] = useState(() => loadCache()?.analysis || null);
  const [webResearch, setWebResearch] = useState(() => loadCache()?.webResearch || null);
  const [scripts, setScripts] = useState(() => loadCache()?.scripts || []);
  const [selectedScript, setSelectedScript] = useState(0);

  // Step 2: Configure
  const [shareToGallery, setShareToGallery] = useState(false);
  const [voices, setVoices] = useState([]);
  const [selectedVoice, setSelectedVoice] = useState('21m00Tcm4TlvDq8ikWAM');
  const [actorDescription, setActorDescription] = useState('');
  const [editedNarration, setEditedNarration] = useState('');
  const [actorOptions, setActorOptions] = useState([]);
  const [selectedActor, setSelectedActor] = useState(null);
  const [generatingActors, setGeneratingActors] = useState(false);
  const [actorGallery, setActorGallery] = useState([]);
  const [loadingGallery, setLoadingGallery] = useState(false);
  const [uploadedActorPreview, setUploadedActorPreview] = useState(null); // {localPreview, serverUrl}

  // Step 3: Generate
  const [generating, setGenerating] = useState(false);
  const [jobId, setJobId] = useState(null);
  const [genLogs, setGenLogs] = useState([]);
  const [genStatus, setGenStatus] = useState('idle');
  const [genResult, setGenResult] = useState(null);

  // Publish
  const [publishing, setPublishing] = useState(false);
  const [publishResult, setPublishResult] = useState(null);
  const [publishPlatforms, setPublishPlatforms] = useState({ tiktok: true, instagram: true, youtube: true });
  const [isScheduling, setIsScheduling] = useState(false);
  const [scheduleDate, setScheduleDate] = useState('');

  // UI
  const [copied, setCopied] = useState('');
  const [logsExpanded, setLogsExpanded] = useState(true);

  // Pre-fill from cache on mount (once: later cache changes must not
  // overwrite what the user typed).
  useEffect(() => {
    if (fromCache && scripts.length > 0 && !actorDescription) {
      setActorDescription(scripts[0].actor_description || '');
      setEditedNarration(scripts[0].full_narration || '');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Fetch actor gallery on mount
  useEffect(() => {
    setLoadingGallery(true);
    fetch(getApiUrl('/api/saasshorts/actor-gallery'))
      .then(res => res.ok ? res.json() : { images: [] })
      .then(data => setActorGallery(data.images || []))
      .catch(() => {})
      .finally(() => setLoadingGallery(false));
  }, []);

  // Fetch voices on mount
  useEffect(() => {
    if (elevenLabsKey) {
      fetchVoices();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [elevenLabsKey]);

  // Reset selected voice when actor gender changes
  useEffect(() => {
    const genderDefaults = {
      'en-female': '21m00Tcm4TlvDq8ikWAM',  // Rachel
      'en-male': '29vD33N1CtxCmqQRPOHJ',    // Drew
      'es-female': 'EXAVITQu4vr4xnSDxMaL',  // Bella
      'es-male': 'ErXwobaYiN019PkySvjV',     // Antoni
    };
    // If we have fetched voices, pick the first matching one; otherwise use hardcoded default
    const matchingVoice = voices.find(v => (v.labels?.gender || '').toLowerCase() === actorGender);
    if (matchingVoice) {
      setSelectedVoice(matchingVoice.voice_id);
    } else {
      setSelectedVoice(genderDefaults[`${language}-${actorGender}`] || genderDefaults['en-female']);
    }
    // Re-pick only when the gender/language choice changes, not on every voices refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [actorGender, language]);

  // Poll generation status
  useEffect(() => {
    let interval;
    if (jobId && genStatus === 'processing') {
      interval = setInterval(async () => {
        try {
          const res = await apiFetch(`/api/saasshorts/status/${jobId}`);
          if (res.status === 404) {
            // Job lost (server restart) — treat as failed so Retry appears
            setGenStatus('failed');
            setGenerating(false);
            setGenLogs((prev) => [...prev, 'Job lost after server restart. Click Retry to resume from cached assets.']);
            clearInterval(interval);
            return;
          }
          if (!res.ok) return;
          const data = await res.json();
          if (data.logs) setGenLogs(data.logs);
          if (data.status === 'completed') {
            setGenStatus('completed');
            setGenResult(data.result);
            setGenerating(false);
            setStep(4);
            clearInterval(interval);
          } else if (data.status === 'failed') {
            setGenStatus('failed');
            setGenerating(false);
            clearInterval(interval);
          }
        } catch (e) {
          console.error('Poll error:', e);
        }
      }, 2000);
    }
    return () => clearInterval(interval);
  }, [jobId, genStatus]);

  const fetchVoices = async () => {
    try {
      const res = await fetch(getApiUrl('/api/saasshorts/voices'), {
        headers: { 'X-ElevenLabs-Key': elevenLabsKey },
      });
      if (res.ok) {
        const data = await res.json();
        setVoices(data.voices || []);
      }
    } catch (e) {
      console.error('Voices fetch error:', e);
    }
  };

  const handleAnalyze = async () => {
    if (!url.trim() && !description.trim()) return;
    if (needsGeminiKey) {
      setAnalyzeError('Gemini API key required. Set it in Settings.');
      return;
    }

    setAnalyzing(true);
    setAnalyzeError('');

    try {
      const res = await apiFetch('/api/saasshorts/analyze', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...geminiHeader,
        },
        body: JSON.stringify({
          url: url.trim() || undefined,
          description: description.trim() || undefined,
          num_scripts: numScripts,
          style,
          language,
          actor_gender: actorGender,
        }),
      });

      if (!res.ok) {
        let msg = 'Analysis failed';
        try { const err = await res.json(); msg = err.detail || msg; } catch { msg = await res.text() || msg; }
        throw new Error(msg);
      }

      const data = await res.json();
      setAnalysis(data.analysis);
      setWebResearch(data.web_research || null);
      setScripts(data.scripts);
      setSelectedScript(0);
      setFromCache(false);

      // Cache results
      saveCache(url.trim(), data.analysis, data.web_research, data.scripts);

      // Pre-fill actor description and narration from first script
      if (data.scripts.length > 0) {
        setActorDescription(data.scripts[0].actor_description || '');
        setEditedNarration(data.scripts[0].full_narration || '');
      }

      setStep(1);
    } catch (e) {
      setAnalyzeError(e.message);
    } finally {
      setAnalyzing(false);
    }
  };

  const handleSelectScript = (idx) => {
    setSelectedScript(idx);
    if (scripts[idx]) {
      setActorDescription(scripts[idx].actor_description || '');
      setEditedNarration(scripts[idx].full_narration || '');
    }
  };

  const handleGenerate = async () => {
    if (!falKey) {
      alert('fal.ai API key required. Set it in Settings.');
      return;
    }
    if (!elevenLabsKey) {
      alert('ElevenLabs API key required. Set it in Settings.');
      return;
    }

    setGenerating(true);
    setGenLogs(['Starting video generation...']);
    setGenStatus('processing');
    setGenResult(null);
    setStep(3);

    try {
      // Update script with edited narration
      const scriptToSend = { ...scripts[selectedScript] };
      scriptToSend._product_name = analysis?.product_name || analysis?.name || '';
      scriptToSend._product_url = url;
      if (editedNarration !== scriptToSend.full_narration) {
        scriptToSend.full_narration = editedNarration;
      }

      const res = await apiFetch('/api/saasshorts/generate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Fal-Key': falKey,
          'X-ElevenLabs-Key': elevenLabsKey,
        },
        body: JSON.stringify({
          script: scriptToSend,
          voice_id: selectedVoice,
          actor_description: actorDescription || undefined,
          selected_actor_url: selectedActor || undefined,
          video_mode: videoMode,
          share_to_gallery: shareToGallery,
        }),
      });

      if (!res.ok) {
        let msg = 'Generation failed';
        try { const err = await res.json(); msg = err.detail || msg; } catch { msg = await res.text() || msg; }
        throw new Error(msg);
      }

      const data = await res.json();
      setJobId(data.job_id);
    } catch (e) {
      setGenStatus('failed');
      setGenLogs((prev) => [...prev, `Error: ${e.message}`]);
      setGenerating(false);
    }
  };

  const handleRetry = async () => {
    if (!jobId) return;
    setGenerating(true);
    setGenLogs(['Retrying from cached assets...']);
    setGenStatus('processing');
    setGenResult(null);

    try {
      const scriptToSend = { ...scripts[selectedScript] };
      scriptToSend._product_name = analysis?.product_name || analysis?.name || '';
      scriptToSend._product_url = url;
      if (editedNarration !== scriptToSend.full_narration) {
        scriptToSend.full_narration = editedNarration;
      }

      const res = await apiFetch('/api/saasshorts/generate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Fal-Key': falKey,
          'X-ElevenLabs-Key': elevenLabsKey,
        },
        body: JSON.stringify({
          script: scriptToSend,
          voice_id: selectedVoice,
          actor_description: actorDescription || undefined,
          retry_job_id: jobId,
          video_mode: videoMode,
          share_to_gallery: shareToGallery,
        }),
      });

      if (!res.ok) {
        let msg = 'Retry failed';
        try { const err = await res.json(); msg = err.detail || msg; } catch { msg = await res.text() || msg; }
        throw new Error(msg);
      }

      const data = await res.json();
      setJobId(data.job_id);
    } catch (e) {
      setGenStatus('failed');
      setGenLogs((prev) => [...prev, `Retry error: ${e.message}`]);
      setGenerating(false);
    }
  };

  const handleCopy = (text, label) => {
    navigator.clipboard.writeText(text);
    setCopied(label);
    setTimeout(() => setCopied(''), 2000);
  };

  const handleReset = () => {
    setStep(0);
    setUrl('');
    setAnalyzeError('');
    setAnalysis(null);
    setWebResearch(null);
    setScripts([]);
    setFromCache(false);
    localStorage.removeItem(CACHE_KEY);
    setSelectedScript(0);
    setJobId(null);
    setGenLogs([]);
    setGenStatus('idle');
    setGenResult(null);
    setGenerating(false);
    setActorDescription('');
    setEditedNarration('');
  };

  // ─── Render Steps ─────────────────────────────────────────────────

  return (
    <div className="h-full overflow-y-auto custom-scrollbar">
      <div className="max-w-5xl mx-auto px-4 py-6 sm:p-8">
        {/* Where we are in the wizard */}
        <div className="mb-8 sm:mb-10">
          <div className="flex items-center justify-between gap-3 mb-4 min-h-[36px]">
            <p className="readout">Step {step + 1} of {STEPS.length} · {STEPS[step]}</p>
            {step > 0 && (
              <button type="button" onClick={handleReset} className="btn-quiet text-xs">
                <RefreshCw size={14} aria-hidden="true" /> Start over
              </button>
            )}
          </div>
          <StepIndicator steps={STEPS} current={step} />
        </div>

        {/* ── Step 0: the brief ───────────────────────────────── */}
        {step === 0 && (
          <section aria-labelledby="ais-brief-title" className="animate-fade">
            <StepHeading id="ais-brief-title" eyebrow="Brief" title="What should the short be about?">
              Give us a website, a description, or both. We research the product, find the pain points your
              audience feels and write scripts an AI actor can perform.
            </StepHeading>

            <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_15rem] lg:gap-12">
              <div className="min-w-0 space-y-10">
                {/* The brief itself: the one feature card of this step */}
                <div className="card-print p-4 sm:p-6 space-y-5">
                  <div>
                    <label htmlFor="ais-url" className="block text-sm font-medium text-ink mb-1.5">
                      Website <span className="font-normal text-muted">(optional)</span>
                    </label>
                    <div className="relative">
                      <Globe size={16} aria-hidden="true" className="absolute left-3 top-1/2 -translate-y-1/2 text-muted pointer-events-none" />
                      <input
                        id="ais-url"
                        type="url"
                        value={url}
                        onChange={(e) => setUrl(e.target.value)}
                        placeholder="https://your-website.com"
                        className="input-field pl-10"
                        aria-describedby="ais-url-help"
                        onKeyDown={(e) => e.key === 'Enter' && handleAnalyze()}
                      />
                    </div>
                    <p id="ais-url-help" className="text-xs text-muted mt-1.5">If you add one, we scrape and research the site for you.</p>
                  </div>

                  <div>
                    <label htmlFor="ais-description" className="block text-sm font-medium text-ink mb-1.5">
                      {url.trim() ? 'Extra context' : 'Describe the product or business'}{' '}
                      <span className="font-normal text-muted">{url.trim() ? '(optional)' : '(required without a website)'}</span>
                    </label>
                    <textarea
                      id="ais-description"
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      rows={3}
                      className="input-field resize-none text-sm"
                      placeholder="e.g. artisan pizzeria in Madrid, productivity coach, sportswear store, meditation app..."
                    />
                  </div>
                </div>

                {/* Video mode */}
                <div>
                  <SubHeading id="ais-mode-title" title="Video mode" hint="How the actor is filmed, and what each video costs." />
                  <div role="radiogroup" aria-labelledby="ais-mode-title" className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4 mt-4">
                    <button
                      type="button"
                      role="radio"
                      aria-checked={videoMode === 'lowcost'}
                      onClick={() => setVideoMode('lowcost')}
                      className={`${choiceCard(videoMode === 'lowcost')} p-4 sm:p-5`}
                    >
                      <ChoiceMark active={videoMode === 'lowcost'} />
                      <span className="flex flex-wrap items-center gap-2 pr-9">
                        <span className="text-base font-semibold text-ink">Low cost</span>
                        <span className={TAG}>Recommended</span>
                      </span>
                      <span className={`readout block mt-2 ${videoMode === 'lowcost' ? 'text-ink2' : ''}`}>~$0.80 / video</span>
                      <span className={`block text-sm leading-relaxed mt-2 ${videoMode === 'lowcost' ? 'text-ink2' : 'text-muted'}`}>
                        Hailuo 2.3 img2video + VEED Lipsync. Good movement and lip-sync.
                      </span>
                    </button>
                    <button
                      type="button"
                      role="radio"
                      aria-checked={videoMode === 'premium'}
                      onClick={() => setVideoMode('premium')}
                      className={`${choiceCard(videoMode === 'premium')} p-4 sm:p-5`}
                    >
                      <ChoiceMark active={videoMode === 'premium'} />
                      <span className="flex flex-wrap items-center gap-2 pr-9">
                        <span className="text-base font-semibold text-ink">Premium</span>
                        <span className={TAG}>Best quality</span>
                      </span>
                      <span className={`readout block mt-2 ${videoMode === 'premium' ? 'text-ink2' : ''}`}>~$2.00 / video</span>
                      <span className={`block text-sm leading-relaxed mt-2 ${videoMode === 'premium' ? 'text-ink2' : 'text-muted'}`}>
                        Kling Avatar v2 Standard. Full, integrated movement.
                      </span>
                    </button>
                  </div>
                </div>

                {/* Language + actor */}
                <div className="grid gap-8 sm:grid-cols-2">
                  <div>
                    <SubHeading id="ais-lang-title" title="Language" />
                    <div className="mt-3" role="group" aria-labelledby="ais-lang-title">
                      <SegmentedControl
                        options={[
                          { value: 'en', label: 'English' },
                          { value: 'es', label: 'Español' },
                        ]}
                        value={language}
                        onChange={setLanguage}
                      />
                    </div>
                  </div>
                  <div>
                    <SubHeading id="ais-gender-title" title="Actor" />
                    <div className="mt-3" role="group" aria-labelledby="ais-gender-title">
                      <SegmentedControl
                        options={[
                          { value: 'female', label: 'Woman' },
                          { value: 'male', label: 'Man' },
                        ]}
                        value={actorGender}
                        onChange={setActorGender}
                      />
                    </div>
                  </div>
                </div>

                {/* Style */}
                <div>
                  <SubHeading id="ais-style-title" title="Style" hint="The shape of the script." />
                  <div role="radiogroup" aria-labelledby="ais-style-title" className="grid grid-cols-2 sm:grid-cols-3 gap-3 mt-4">
                    {STYLE_OPTIONS.map((s) => (
                      <button
                        key={s.id}
                        type="button"
                        role="radio"
                        aria-checked={style === s.id}
                        onClick={() => setStyle(s.id)}
                        className={`${choiceCard(style === s.id)} p-3 sm:p-4`}
                      >
                        <ChoiceMark active={style === s.id} small />
                        <span className="block text-sm font-semibold text-ink pr-7 break-words">{s.label}</span>
                        <span className={`block text-xs leading-snug mt-1 ${style === s.id ? 'text-ink2' : 'text-muted'}`}>{s.desc}</span>
                      </button>
                    ))}
                  </div>
                </div>

                {/* Number of scripts */}
                <div>
                  <SubHeading id="ais-count-title" title="How many scripts?" hint="We write several takes; you pick the one to film." />
                  <div className="mt-3 max-w-xs" role="group" aria-labelledby="ais-count-title">
                    <SegmentedControl
                      options={[1, 2, 3, 5].map((n) => ({ value: n, label: String(n) }))}
                      value={numScripts}
                      onChange={setNumScripts}
                      size="sm"
                    />
                  </div>
                </div>

                <div className="space-y-3 pt-6 border-t border-rule2">
                  {analyzeError && (
                    <div role="alert" className="flex items-start gap-2 text-sm text-danger bg-danger/10 border border-danger/30 rounded-input p-3">
                      <AlertCircle size={16} className="shrink-0 mt-0.5" aria-hidden="true" />
                      <span className="min-w-0 break-words">{analyzeError}</span>
                    </div>
                  )}
                  <div className="flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-4">
                    <button
                      type="button"
                      onClick={handleAnalyze}
                      disabled={analyzing || (!url.trim() && !description.trim())}
                      className="btn-primary w-full sm:w-auto"
                    >
                      {analyzing ? (
                        <>
                          <Loader2 size={16} className="animate-spin" aria-hidden="true" />
                          {url.trim() ? 'Researching…' : 'Writing scripts…'}
                        </>
                      ) : (
                        <>
                          {url.trim() ? 'Research and write scripts' : 'Write scripts'}
                          <ChevronRight size={16} aria-hidden="true" />
                        </>
                      )}
                    </button>
                    <p className="readout" aria-live="polite">
                      {analyzing
                        ? (url.trim() ? 'Scraping the site, researching the web, writing scripts · 45–90 s' : 'Writing scripts · 20–40 s')
                        : (url.trim() ? 'Takes about 45–90 s' : 'Takes about 20–40 s')}
                    </p>
                  </div>
                </div>
              </div>

              {/* How it works */}
              <aside aria-labelledby="ais-how-title" className="lg:sticky lg:top-8 self-start lg:border-l lg:border-rule lg:pl-8">
                <h3 id="ais-how-title" className="readout">How it works</h3>
                <ol className="mt-3 divide-y divide-rule border-y border-rule lg:border-y-0">
                  <li className="py-4 lg:pt-1">
                    <h4 className="text-sm font-semibold text-ink">Deep research</h4>
                    <p className="text-sm text-muted mt-1 leading-relaxed">
                      AI analyzes your product from its website and the web, or works straight from your description.
                    </p>
                  </li>
                  <li className="py-4">
                    <h4 className="text-sm font-semibold text-ink">Pain-point scripts</h4>
                    <p className="text-sm text-muted mt-1 leading-relaxed">
                      Hook, problem, solution: scripts aimed at the real pain points of your audience.
                    </p>
                  </li>
                  <li className="py-4">
                    <h4 className="text-sm font-semibold text-ink">AI actor videos</h4>
                    <p className="text-sm text-muted mt-1 leading-relaxed">
                      Realistic AI actors with lip-sync, b-roll and captions. From ~$0.50 a video.
                    </p>
                  </li>
                </ol>
              </aside>
            </div>
          </section>
        )}

        {/* ── Step 1: analysis + scripts ──────────────────────── */}
        {step === 1 && analysis && (
          <div className="animate-fade space-y-12">
            <section aria-labelledby="ais-analysis-title">
              <StepHeading id="ais-analysis-title" eyebrow="Analysis" title={analysis.product_name || 'Analysis'}>
                {analysis.one_liner}
              </StepHeading>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2 -mt-3 mb-6">
                {analysis.industry && <span className={TAG}>{analysis.industry}</span>}
                {fromCache && (
                  <>
                    <span className={TAG}>Cached result</span>
                    <button
                      type="button"
                      onClick={() => { setStep(0); setFromCache(false); }}
                      className="inline-flex items-center gap-1.5 text-xs font-medium text-cobalt underline underline-offset-2 hover:text-ink transition-colors min-h-[44px] sm:min-h-0"
                    >
                      <RefreshCw size={12} aria-hidden="true" /> Re-analyze
                    </button>
                  </>
                )}
              </div>

              <div className="grid gap-8 md:grid-cols-2 md:gap-10 border-t border-rule2 pt-6">
                <div>
                  <h3 className="text-base font-semibold text-ink">Pain points</h3>
                  <ul className="mt-3 divide-y divide-rule border-y border-rule">
                    {(analysis.pain_points || []).map((pp, i) => (
                      <li key={i} className="flex items-start gap-3 py-2.5 text-sm">
                        <span className="mt-1.5 flex gap-0.5 shrink-0" title={pp.intensity} aria-hidden="true">
                          {[0, 1, 2].map((d) => (
                            <span
                              key={d}
                              className={`w-1.5 h-1.5 rounded-full ${
                                d < (pp.intensity === 'high' ? 3 : pp.intensity === 'medium' ? 2 : 1)
                                  ? 'bg-ink'
                                  : 'bg-[color:var(--color-rule-2)]'
                              }`}
                            />
                          ))}
                        </span>
                        <span className="min-w-0">
                          {pp.intensity && <span className="sr-only">Intensity {pp.intensity}: </span>}
                          <span className="text-ink2">{pp.pain}</span>
                          {pp.source && pp.source !== 'website' && (
                            <span className="ml-1.5 readout">{pp.source}</span>
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <h3 className="text-base font-semibold text-ink">Emotional hooks</h3>
                  <ul className="mt-3 divide-y divide-rule border-y border-rule">
                    {(analysis.emotional_hooks || []).map((h, i) => (
                      <li key={i} className="text-sm text-ink2 py-2.5 leading-relaxed">
                        {h}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </section>

            {/* Web research */}
            {webResearch && (
              <section aria-labelledby="ais-research-title" className="tray p-4 sm:p-6">
                <div className="flex flex-wrap items-baseline justify-between gap-2 mb-5">
                  <h3 id="ais-research-title" className="text-base font-semibold text-ink">Web research</h3>
                  {webResearch.grounding_sources && (
                    <span className="readout">
                      {webResearch.grounding_sources.length} sources
                    </span>
                  )}
                </div>

                {/* Real user reviews */}
                {webResearch.real_reviews && webResearch.real_reviews.length > 0 && (
                  <div className="mb-6">
                    <h4 className="readout mb-3">Real user reviews</h4>
                    <div className="grid gap-3 sm:grid-cols-2">
                      {webResearch.real_reviews.slice(0, 5).map((review, i) => (
                        <figure key={i} className="bg-paper2 border border-rule rounded-input p-3.5">
                          <blockquote className="text-sm text-ink2 leading-relaxed">&ldquo;{review.quote}&rdquo;</blockquote>
                          <figcaption className="flex flex-wrap items-center gap-2 mt-2">
                            <span className="text-xs text-muted">{review.source}</span>
                            <span className="readout">· {review.sentiment}</span>
                          </figcaption>
                        </figure>
                      ))}
                    </div>
                  </div>
                )}

                {/* Competitors */}
                {webResearch.competitors && webResearch.competitors.length > 0 && (
                  <div className="mb-6">
                    <h4 className="readout mb-3">Competitors</h4>
                    <ul className="flex flex-wrap gap-2">
                      {webResearch.competitors.map((c, i) => (
                        <li key={i} className="text-xs bg-paper2 border border-rule2 px-2 py-1 rounded text-ink2" title={c.comparison}>
                          {c.name}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Sources */}
                {webResearch.grounding_sources && webResearch.grounding_sources.length > 0 && (
                  <div>
                    <h4 className="readout mb-3">Sources</h4>
                    <ul className="flex flex-wrap gap-x-4 gap-y-2">
                      {webResearch.grounding_sources.slice(0, 8).map((src, i) => (
                        <li key={i} className="min-w-0">
                          <a
                            href={src.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-block align-bottom text-xs text-cobalt underline underline-offset-2 hover:text-ink transition-colors truncate max-w-[220px]"
                            title={src.title}
                          >
                            {src.title || (() => { try { return new URL(src.url).hostname; } catch { return src.url; } })()}
                          </a>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </section>
            )}

            {/* Scripts */}
            <section aria-labelledby="ais-scripts-title">
              <div className="flex flex-wrap items-end justify-between gap-3 mb-5">
                <div>
                  <h2 id="ais-scripts-title" className="font-display text-2xl text-ink leading-tight">Pick the script to film</h2>
                  <p className="text-sm text-muted mt-1.5">You can still edit its narration in the next step.</p>
                </div>
                <span className="readout">{scripts.length} scripts</span>
              </div>

              <div className="space-y-4">
                {scripts.map((script, i) => (
                  <article key={i} className={`${choiceCard(selectedScript === i)} p-4 sm:p-6`}>
                    <ChoiceMark active={selectedScript === i} />
                    <div className="flex items-start gap-4 sm:gap-5">
                      <span aria-hidden="true" className="font-quote text-4xl sm:text-5xl leading-none text-ink w-7 sm:w-9 shrink-0 -mt-1">
                        {i + 1}
                      </span>
                      <div className="min-w-0 flex-1">
                        <h3 className="pr-9">
                          {/* The title is the control; its ::after stretches over the whole card. */}
                          <button
                            type="button"
                            aria-pressed={selectedScript === i}
                            onClick={() => handleSelectScript(i)}
                            className="text-left text-base sm:text-lg font-semibold text-ink leading-snug after:absolute after:inset-0 after:rounded-card after:content-['']"
                          >
                            {script.title}
                          </button>
                        </h3>
                        <p className={`readout mt-1.5 ${selectedScript === i ? 'text-ink2' : ''}`}>
                          {script.duration_seconds}s &middot; {script.style} &middot; {script.target_platform}
                        </p>

                        {/* Segment timeline */}
                        <div className="flex gap-1 mt-4" aria-hidden="true">
                          {(script.segments || []).map((seg, j) => (
                            <div
                              key={j}
                              className={`h-1.5 rounded-sm ${
                                seg.type === 'hook' ? 'bg-ink' :
                                seg.type === 'problem' ? 'bg-ink/60' :
                                seg.type === 'solution' ? 'bg-ink/35' :
                                'bg-ink/20'
                              }`}
                              style={{ flex: (seg.end - seg.start) }}
                              title={`${seg.type}: ${seg.start}s-${seg.end}s`}
                            />
                          ))}
                        </div>

                        <dl className="mt-4 space-y-2">
                          {(script.segments || []).map((seg, j) => (
                            <div key={j} className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-3 text-sm">
                              <dt className={`readout pt-0.5 ${selectedScript === i ? 'text-ink2' : ''}`}>{seg.type}</dt>
                              <dd className="text-ink2 leading-relaxed">{seg.narration}</dd>
                            </div>
                          ))}
                        </dl>

                        {/* Hook text & hashtags */}
                        <div className="mt-4 pt-3 border-t border-rule flex flex-wrap items-baseline gap-x-3 gap-y-1.5">
                          <span className={`readout ${selectedScript === i ? 'text-ink2' : ''}`}>Hook</span>
                          <span className="text-sm text-ink">&ldquo;{script.hook_text}&rdquo;</span>
                          {(script.hashtags || []).slice(0, 4).map((tag, j) => (
                            <span key={j} className={`readout normal-case ${selectedScript === i ? 'text-ink2' : ''}`}>{tag}</span>
                          ))}
                        </div>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </section>

            <div className="flex flex-col-reverse sm:flex-row sm:items-center sm:justify-between gap-3 pt-6 border-t border-rule2">
              <button type="button" onClick={() => setStep(0)} className="btn-ghost">
                <ChevronLeft size={16} aria-hidden="true" /> Back
              </button>
              <button type="button" onClick={() => setStep(2)} className="btn-primary">
                Choose actor and voice <ChevronRight size={16} aria-hidden="true" />
              </button>
            </div>
          </div>
        )}

        {/* ── Step 2: cast & voice ────────────────────────────── */}
        {step === 2 && scripts[selectedScript] && (
          <section aria-labelledby="ais-cast-title" className="animate-fade">
            <StepHeading id="ais-cast-title" eyebrow="Cast" title="Who performs it, and how it sounds">
              Script: <span className="text-ink2 font-medium">{scripts[selectedScript].title}</span>
            </StepHeading>

            <div className="grid gap-10 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] lg:gap-12">
              {/* Actor */}
              <div className="min-w-0">
                <SubHeading id="ais-actor-title" title="Actor" hint="Pick an earlier actor, upload a photo or generate new ones." />

                {/* Existing gallery */}
                {actorGallery.length > 0 && (
                  <div className="mt-4">
                    <p className="readout mb-2">Your earlier actors</p>
                    <div role="group" aria-labelledby="ais-actor-title" className="grid grid-cols-4 sm:grid-cols-5 gap-2 max-h-60 overflow-y-auto custom-scrollbar pr-1">
                      {actorGallery.map((img, i) => (
                        <button
                          key={img.url}
                          type="button"
                          aria-pressed={selectedActor === img.url}
                          onClick={() => setSelectedActor(img.url)}
                          className={`relative rounded-input overflow-hidden border-2 bg-black transition-colors duration-200 aspect-[3/4] ${
                            selectedActor === img.url ? 'border-vermilion' : 'border-rule2 hover:border-ink/50'
                          }`}
                        >
                          <img src={img.url} alt={`Actor ${i + 1}`} className="w-full h-full object-cover" />
                          {selectedActor === img.url && <ImageCheck />}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {loadingGallery && (
                  <p role="status" className="text-xs text-muted mt-4 flex items-center gap-1.5">
                    <Loader2 size={14} className="animate-spin" aria-hidden="true" /> Loading your actors…
                  </p>
                )}

                {/* Upload a custom actor */}
                <div className="mt-4 flex items-center gap-3">
                  <label className="flex-1 min-h-[48px] flex items-center justify-center gap-2 text-sm text-ink2 px-4 py-3 rounded-input border border-dashed border-rule2 hover:border-ink/50 hover:text-ink transition-colors duration-200 cursor-pointer focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-[color:var(--color-focus)]">
                    <Upload size={16} className="text-muted" aria-hidden="true" />
                    <span>Upload your own photo</span>
                    <input
                      type="file"
                      accept="image/*"
                      className="sr-only"
                      onChange={async (e) => {
                        const file = e.target.files?.[0];
                        if (!file) return;
                        // Show instant preview
                        const localPreview = URL.createObjectURL(file);
                        setUploadedActorPreview({ localPreview, serverUrl: null });
                        setSelectedActor(null);

                        const formData = new FormData();
                        formData.append('file', file);
                        try {
                          const res = await apiFetch('/api/saasshorts/actor-upload', {
                            method: 'POST',
                            body: formData,
                          });
                          if (res.ok) {
                            const data = await res.json();
                            if (data.url) {
                              setUploadedActorPreview({ localPreview, serverUrl: data.url });
                              setSelectedActor(data.url);
                            }
                          }
                        } catch (err) { console.error('Upload failed:', err); }
                        e.target.value = '';
                      }}
                    />
                  </label>
                  {uploadedActorPreview && (
                    <button
                      type="button"
                      aria-pressed={selectedActor === uploadedActorPreview.serverUrl}
                      aria-label={uploadedActorPreview.serverUrl ? 'Use your uploaded photo' : 'Uploading your photo'}
                      onClick={() => {
                        if (uploadedActorPreview.serverUrl) {
                          setSelectedActor(uploadedActorPreview.serverUrl);
                        }
                      }}
                      className={`relative w-16 h-20 rounded-input overflow-hidden border-2 bg-black transition-colors duration-200 flex-shrink-0 ${
                        selectedActor === uploadedActorPreview.serverUrl
                          ? 'border-vermilion'
                          : 'border-rule2 hover:border-ink/50'
                      }`}
                    >
                      <img src={uploadedActorPreview.localPreview} alt="" className="w-full h-full object-cover" />
                      {selectedActor === uploadedActorPreview.serverUrl && <ImageCheck />}
                      {!uploadedActorPreview.serverUrl && (
                        <span className="absolute inset-0 bg-paper/70 flex items-center justify-center">
                          <Loader2 size={16} className="animate-spin text-ink" aria-hidden="true" />
                        </span>
                      )}
                    </button>
                  )}
                </div>

                {/* Generate new actors */}
                <div className="mt-6">
                  <label htmlFor="ais-actor-desc" className="block text-sm font-medium text-ink mb-1.5">
                    {actorGallery.length > 0 ? 'Or generate new actors' : 'Or describe your actor'}
                  </label>
                  <textarea
                    id="ais-actor-desc"
                    value={actorDescription}
                    onChange={(e) => { setActorDescription(e.target.value); setActorOptions([]); }}
                    rows={2}
                    className="input-field resize-none text-sm"
                    placeholder="e.g. A young woman in her late 20s, dark hair, casual outfit..."
                  />

                  <button
                    type="button"
                    onClick={async () => {
                      if (!falKey || !actorDescription) return;
                      setGeneratingActors(true);
                      setActorOptions([]);
                      setSelectedActor(null);
                      try {
                        const res = await apiFetch('/api/saasshorts/actor-options', {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json', 'X-Fal-Key': falKey },
                          body: JSON.stringify({ actor_description: actorDescription, num_options: 3 }),
                        });
                        if (res.ok) {
                          const data = await res.json();
                          setActorOptions(data.images || []);
                          // Refresh gallery to include newly uploaded actors
                          const galRes = await fetch(getApiUrl('/api/saasshorts/actor-gallery'));
                          if (galRes.ok) {
                            const galData = await galRes.json();
                            setActorGallery(galData.images || []);
                          }
                        }
                      } catch (e) { console.error(e); }
                      finally { setGeneratingActors(false); }
                    }}
                    disabled={generatingActors || !falKey || !actorDescription}
                    className="btn-ghost mt-3 w-full"
                  >
                    {generatingActors ? (
                      <><Loader2 size={16} className="animate-spin" aria-hidden="true" /> Generating 3 actors…</>
                    ) : (
                      <><User size={16} aria-hidden="true" /> {actorOptions.length > 0 ? 'Regenerate actors' : 'Generate 3 new actors'} <span className="readout">~$0.06</span></>
                    )}
                  </button>
                </div>

                {/* Newly generated actor options */}
                {actorOptions.length > 0 && (
                  <div className="mt-5">
                    <p className="readout mb-2">New actors · pick one</p>
                    <div className="grid grid-cols-3 gap-3">
                      {actorOptions.map((imgUrl, i) => (
                        <button
                          key={imgUrl}
                          type="button"
                          aria-pressed={selectedActor === imgUrl}
                          onClick={() => setSelectedActor(imgUrl)}
                          className={`relative rounded-card overflow-hidden border-2 bg-black transition-colors duration-200 aspect-[9/16] ${
                            selectedActor === imgUrl ? 'border-vermilion' : 'border-rule2 hover:border-ink/50'
                          }`}
                        >
                          <img src={imgUrl} alt={`New actor ${i + 1}`} className="w-full h-full object-cover" />
                          {selectedActor === imgUrl && <ImageCheck />}
                          <span className="absolute bottom-1.5 left-1.5 readout text-ink2 bg-paper border border-rule2 px-1.5 py-0.5 rounded" aria-hidden="true">
                            New {i + 1}
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {!selectedActor && (actorOptions.length > 0 || actorGallery.length > 0) && (
                  <p className="text-sm text-warn mt-3 flex items-center gap-1.5">
                    <AlertCircle size={14} aria-hidden="true" /> Select an actor to continue
                  </p>
                )}
              </div>

              {/* Voice + narration */}
              <div className="min-w-0 space-y-10">
                <div>
                  <div className="flex items-baseline justify-between gap-3">
                    <h3 id="ais-voice-title" className="font-display text-lg text-ink">Voice</h3>
                    <span className="readout">{language === 'es' ? 'Spanish' : 'English'}</span>
                  </div>
                  <div className="mt-3">
                    {(() => {
                      // Filter voices by language/accent
                      const filtered = voices.length > 0
                        ? voices.filter((v) => {
                            const gender = (v.labels?.gender || '').toLowerCase();
                            // Only show voices that match the selected gender
                            return gender === actorGender;
                          })
                          .sort((a, b) => {
                            const aAccent = (a.labels?.accent || '').toLowerCase();
                            const bAccent = (b.labels?.accent || '').toLowerCase();
                            if (language === 'es') {
                              // Spanish/latin accents first, then everything else
                              const aScore = (aAccent.includes('spanish') || aAccent.includes('latin')) ? 0 : 1;
                              const bScore = (bAccent.includes('spanish') || bAccent.includes('latin')) ? 0 : 1;
                              return aScore - bScore;
                            }
                            // English: american/british first
                            const aScore = (aAccent.includes('american') || aAccent.includes('british')) ? 0 : 1;
                            const bScore = (bAccent.includes('american') || bAccent.includes('british')) ? 0 : 1;
                            return aScore - bScore;
                          })
                        : [];

                      if (filtered.length > 0) {
                        return (
                          <div role="group" aria-labelledby="ais-voice-title" className="space-y-1.5 max-h-72 overflow-y-auto custom-scrollbar pr-1">
                            {filtered.map((v) => (
                              <div
                                key={v.voice_id}
                                className={`flex items-center rounded-input border transition-colors duration-200 ${
                                  selectedVoice === v.voice_id
                                    ? 'border-vermilion bg-vermilionsoft'
                                    : 'border-rule bg-paper2 hover:border-rule2'
                                }`}
                              >
                                <button
                                  type="button"
                                  aria-pressed={selectedVoice === v.voice_id}
                                  onClick={() => setSelectedVoice(v.voice_id)}
                                  className="flex-1 min-w-0 min-h-[44px] flex items-center gap-3 px-3 py-2.5 text-left"
                                >
                                  <span className="flex-1 min-w-0">
                                    <span className={`block text-sm truncate ${selectedVoice === v.voice_id ? 'text-ink font-medium' : 'text-ink2'}`}>{v.name}</span>
                                    <span className={`readout block mt-0.5 truncate ${selectedVoice === v.voice_id ? 'text-ink2' : ''}`}>
                                      {v.labels?.accent || ''} {v.labels?.gender || ''} {v.category ? `· ${v.category}` : ''}
                                    </span>
                                  </span>
                                  {selectedVoice === v.voice_id && <Check size={16} className="text-vermilion shrink-0" aria-hidden="true" />}
                                </button>
                                {v.preview_url && (
                                  <button
                                    type="button"
                                    onClick={(e) => { e.stopPropagation(); new Audio(v.preview_url).play(); }}
                                    className="shrink-0 mr-1.5 w-11 h-11 sm:w-9 sm:h-9 rounded-input text-muted hover:text-ink hover:bg-paper3 flex items-center justify-center transition-colors"
                                    aria-label={`Preview ${v.name}`}
                                    title="Preview voice"
                                  >
                                    <Volume2 size={16} aria-hidden="true" />
                                  </button>
                                )}
                              </div>
                            ))}
                          </div>
                        );
                      }

                      // Fallback defaults by gender + language
                      const defaults = {
                        'en-female': [
                          { id: '21m00Tcm4TlvDq8ikWAM', name: 'Rachel (calm)' },
                          { id: 'EXAVITQu4vr4xnSDxMaL', name: 'Bella (soft)' },
                        ],
                        'en-male': [
                          { id: '29vD33N1CtxCmqQRPOHJ', name: 'Drew (confident)' },
                          { id: 'TxGEqnHWrfWFTfGW9XjX', name: 'Josh (deep)' },
                          { id: 'yoZ06aMxZJJ28mfd3POQ', name: 'Sam (raspy)' },
                        ],
                        'es-female': [
                          { id: 'EXAVITQu4vr4xnSDxMaL', name: 'Bella (suave)' },
                          { id: '21m00Tcm4TlvDq8ikWAM', name: 'Rachel (calmada)' },
                        ],
                        'es-male': [
                          { id: 'ErXwobaYiN019PkySvjV', name: 'Antoni (cálido)' },
                          { id: '29vD33N1CtxCmqQRPOHJ', name: 'Drew (confiado)' },
                        ],
                      };
                      const key = `${language}-${actorGender}`;
                      const opts = defaults[key] || defaults['en-female'];
                      return (
                        <select
                          value={selectedVoice}
                          onChange={(e) => setSelectedVoice(e.target.value)}
                          className="input-field"
                          aria-labelledby="ais-voice-title"
                        >
                          {opts.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                        </select>
                      );
                    })()}
                  </div>
                  <p className="text-xs text-muted mt-2 leading-relaxed">
                    {actorGender === 'female' ? 'Female' : 'Male'} voices &middot; the multilingual model speaks your selected language &middot; use the speaker to preview
                  </p>
                </div>

                <div>
                  <label htmlFor="ais-narration" className="font-display text-lg text-ink block">Narration</label>
                  <textarea
                    id="ais-narration"
                    value={editedNarration}
                    onChange={(e) => setEditedNarration(e.target.value)}
                    rows={7}
                    className="input-field resize-y text-sm leading-relaxed mt-3"
                    aria-describedby="ais-narration-meta"
                  />
                  <p id="ais-narration-meta" className="readout mt-1.5">
                    {editedNarration.length} chars &middot; ~{Math.round(editedNarration.split(' ').length / 2.5)}s speech
                  </p>
                </div>
              </div>
            </div>

            {/* The bill + publishing consent + generate */}
            <div className="mt-10 grid gap-6 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] items-start">
              <div className="tray p-4 sm:p-5">
                <div className="flex items-baseline justify-between gap-3 mb-3">
                  <h3 className="text-sm font-semibold text-ink">Estimated cost</h3>
                  <span className="font-mono text-sm text-ink">~${videoMode === 'lowcost' ? '0.65' : '2.50'}</span>
                </div>
                <dl className="space-y-1.5 border-t border-rule pt-3">
                  {(videoMode === 'lowcost'
                    ? [
                        ['Flux image', '$0.05'],
                        ['ElevenLabs voice', '$0.10'],
                        ['Hailuo 2.3 img2video', '$0.19'],
                        ['VEED Lipsync', '$0.20'],
                        ['Flux b-roll', '$0.10'],
                      ]
                    : [
                        ['Flux image', '$0.05'],
                        ['ElevenLabs voice', '$0.10'],
                        ['Kling avatar', '$1.69'],
                        ['Kling b-roll', '$0.70'],
                      ]
                  ).map(([item, cost]) => (
                    <div key={item} className="flex items-center justify-between gap-3 readout">
                      <dt>{item}</dt>
                      <dd>{cost}</dd>
                    </div>
                  ))}
                </dl>
              </div>

              <div className="space-y-4">
                {/* Missing keys warning */}
                {(!falKey || !elevenLabsKey) && (
                  <div role="alert" className="p-3 bg-warn/10 border border-warn/30 rounded-input flex items-start gap-2 text-sm text-warn">
                    <AlertCircle size={16} className="shrink-0 mt-0.5" aria-hidden="true" />
                    <span>
                      {!falKey && 'fal.ai API key missing. '}{!elevenLabsKey && 'ElevenLabs API key missing. '}
                      Set them in Settings.
                    </span>
                  </div>
                )}

                <label className="flex items-start gap-3 text-sm text-ink cursor-pointer">
                  <input
                    type="checkbox"
                    checked={shareToGallery}
                    onChange={(e) => setShareToGallery(e.target.checked)}
                    className="mt-0.5 w-4 h-4 shrink-0 accent-[var(--color-accent)]"
                  />
                  <span>
                    Share this video in the public gallery
                    <span className="block text-xs text-muted mt-0.5 leading-relaxed">
                      Your video, product name and script will be visible at openshorts.app/gallery
                    </span>
                  </span>
                </label>
              </div>
            </div>

            <div className="mt-8 flex flex-col-reverse sm:flex-row sm:items-center sm:justify-between gap-3 pt-6 border-t border-rule2">
              <button type="button" onClick={() => setStep(1)} className="btn-ghost">
                <ChevronLeft size={16} aria-hidden="true" /> Back
              </button>
              <button
                type="button"
                onClick={handleGenerate}
                disabled={!falKey || !elevenLabsKey || !selectedActor || generating}
                className="btn-accent"
              >
                {generating ? (
                  <><Loader2 size={16} className="animate-spin" aria-hidden="true" /> Generating…</>
                ) : !selectedActor ? (
                  <><User size={16} aria-hidden="true" /> Select an actor first</>
                ) : (
                  <><Film size={16} aria-hidden="true" /> Generate video <span className="font-mono text-xs">~${videoMode === 'lowcost' ? '0.65' : '2.00'}</span></>
                )}
              </button>
            </div>
          </section>
        )}

        {/* ── Step 3: generation progress ─────────────────────── */}
        {step === 3 && (
          <section aria-labelledby="ais-gen-title" className="animate-fade">
            <StepHeading
              id="ais-gen-title"
              eyebrow="Generation"
              title={genStatus === 'failed' ? 'The generation stopped' : genStatus === 'completed' ? 'Your short is ready' : 'Making your short'}
            >
              The talking-head video alone takes 2–5 minutes. Keep this page open: the result appears here.
            </StepHeading>

            <div className="card-print p-4 sm:p-6">
              <div className="flex items-center justify-between gap-3 mb-6">
                <h3 className="text-sm font-semibold text-ink">Pipeline</h3>
                <p role="status" aria-live="polite">
                  <span className="sr-only">Status: </span>
                  <span className={
                    genStatus === 'processing' ? TAG :
                    genStatus === 'completed' ? 'badge-ok' :
                    'badge-danger'
                  }>
                    {STATUS_WORD[genStatus] || genStatus}
                  </span>
                </p>
              </div>

              {/* Progress steps: nodes on a filament */}
              <ol className="mb-6">
                {[
                  'Generating actor image + voiceover',
                  'Creating talking head video (2-5 min)',
                  'Generating b-roll clips',
                  'Compositing final video',
                ].map((label, i, all) => {
                  const logStr = genLogs.join(' ').toLowerCase();
                  const stepDone =
                    i === 0 ? logStr.includes('[2/6]') || logStr.includes('[3/6]') :
                    i === 1 ? logStr.includes('[3/6]') && (logStr.includes('[4/6]') || logStr.includes('talking head ready')) :
                    i === 2 ? logStr.includes('[5/6]') || logStr.includes('[6/6]') :
                    genStatus === 'completed';
                  const stepActive =
                    i === 0 ? logStr.includes('[1/6]') && !stepDone :
                    i === 1 ? (logStr.includes('[3/6]') && !logStr.includes('[4/6]')) :
                    i === 2 ? (logStr.includes('[4/6]') && !logStr.includes('[5/6]') && !logStr.includes('[6/6]')) :
                    logStr.includes('[6/6]') && genStatus !== 'completed';

                  return (
                    <li key={i} className="relative flex items-start gap-4 pb-5 last:pb-0">
                      {i < all.length - 1 && (
                        <span
                          aria-hidden="true"
                          className={`absolute left-[11px] top-6 bottom-0 w-px ${stepDone ? 'bg-ink/70' : 'bg-[color:var(--color-rule-2)]'}`}
                        />
                      )}
                      <span
                        aria-hidden="true"
                        className={`relative z-[1] mt-px w-6 h-6 shrink-0 rounded-full border flex items-center justify-center ${
                          stepDone ? 'bg-ink border-ink text-paper' :
                          stepActive ? 'border-vermilion bg-paper2' :
                          'border-rule2 bg-paper2'
                        }`}
                      >
                        {stepDone ? (
                          <Check size={13} />
                        ) : stepActive ? (
                          <span className="w-2 h-2 rounded-full bg-vermilion motion-safe:animate-pulse" />
                        ) : null}
                      </span>
                      <span className={`text-sm pt-0.5 ${stepDone ? 'text-ink2' : stepActive ? 'text-ink font-medium' : 'text-muted'}`}>
                        {label}
                        <span className="sr-only">{stepDone ? ' (done)' : stepActive ? ' (in progress)' : ' (waiting)'}</span>
                      </span>
                    </li>
                  );
                })}
              </ol>

              {/* Logs */}
              <div className="tray overflow-hidden">
                <div className="px-3 sm:px-4 py-1.5 border-b border-rule flex items-center justify-between gap-3">
                  <span className="readout flex items-center gap-2">
                    <Terminal size={14} aria-hidden="true" /> Generation log
                  </span>
                  <button
                    type="button"
                    onClick={() => setLogsExpanded(!logsExpanded)}
                    aria-expanded={logsExpanded}
                    aria-controls="ais-gen-logs"
                    aria-label={logsExpanded ? 'Hide the log' : 'Show the log'}
                    className="w-11 h-11 sm:w-9 sm:h-9 -mr-1.5 rounded-input flex items-center justify-center text-muted hover:text-ink hover:bg-paper2 transition-colors"
                  >
                    <ChevronDown size={16} aria-hidden="true" className={`transition-transform ${logsExpanded ? 'rotate-180' : ''}`} />
                  </button>
                </div>
                {logsExpanded && (
                  <div id="ais-gen-logs" className="p-3 sm:p-4 max-h-64 overflow-y-auto font-mono text-xs space-y-1 custom-scrollbar break-words">
                    {genLogs.map((log, i) => (
                      <div key={i} className={`${log.toLowerCase().includes('error') ? 'text-danger' : log.includes('✅') ? 'text-ok' : 'text-ink2'}`}>
                        {log}
                      </div>
                    ))}
                    {genStatus === 'processing' && (
                      <div className="motion-safe:animate-pulse text-muted" aria-hidden="true">_</div>
                    )}
                  </div>
                )}
              </div>

              {/* Retry when failed */}
              {genStatus === 'failed' && (
                <div role="alert" className="mt-5 p-4 border border-danger/40 bg-danger/10 rounded-card space-y-3">
                  <p className="flex items-start gap-2 text-sm text-danger">
                    <AlertCircle size={16} className="shrink-0 mt-0.5" aria-hidden="true" />
                    Generation failed. Retry from the cached assets, or go back and change the settings.
                  </p>
                  <div className="flex flex-col sm:flex-row gap-3">
                    <button
                      type="button"
                      onClick={() => { setStep(2); setGenStatus('idle'); setGenerating(false); }}
                      className="btn-ghost"
                    >
                      <ChevronLeft size={16} aria-hidden="true" /> Change voice or settings
                    </button>
                    <button
                      type="button"
                      onClick={handleRetry}
                      disabled={generating}
                      className="btn-primary"
                    >
                      <RefreshCw size={16} aria-hidden="true" /> Retry
                    </button>
                  </div>
                </div>
              )}
            </div>
          </section>
        )}

        {/* ── Step 4: result ──────────────────────────────────── */}
        {step === 4 && genResult && (
          <section aria-labelledby="ais-result-title" className="animate-fade">
            <StepHeading id="ais-result-title" eyebrow="Result" title="Your short is ready" />

            <div className="mb-8">
              <StarBanner message="Happy with your short?" />
            </div>

            <div className="grid gap-8 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)] lg:gap-12">
              {/* The video, on black */}
              <figure className="w-full max-w-[20rem] mx-auto lg:mx-0">
                <div className="aspect-[9/16] bg-black border border-rule2 rounded-card overflow-hidden">
                  <video
                    src={getApiUrl(genResult.video_url)}
                    controls
                    className="w-full h-full object-contain"
                    autoPlay
                  />
                </div>
                <figcaption className="readout mt-2">
                  {genResult.duration?.toFixed(1)}s &middot; 9:16 vertical
                </figcaption>
              </figure>

              {/* Details */}
              <div className="min-w-0 space-y-8">
                <div>
                  <h3 className="text-xl font-semibold text-ink leading-snug">{genResult.script?.title}</h3>
                  <div className="flex flex-wrap gap-3 mt-4">
                    <a
                      href={getApiUrl(genResult.video_url)}
                      download
                      className="btn-primary"
                    >
                      <Download size={16} aria-hidden="true" /> Download
                    </a>
                    <button
                      type="button"
                      onClick={handleReset}
                      className="btn-ghost"
                    >
                      <RefreshCw size={16} aria-hidden="true" /> New video
                    </button>
                  </div>
                </div>

                {/* Caption */}
                {genResult.script?.caption && (
                  <div>
                    <div className="flex items-center justify-between gap-3 mb-2">
                      <h4 className="readout">Caption</h4>
                      <CopyButton done={copied === 'caption'} onClick={() => handleCopy(genResult.script.caption, 'caption')} what="caption" />
                    </div>
                    <p className="text-sm text-ink2 bg-paper2 border border-rule rounded-input p-3 leading-relaxed break-words">{genResult.script.caption}</p>
                  </div>
                )}

                {/* Hashtags */}
                {genResult.script?.hashtags && (
                  <div>
                    <div className="flex items-center justify-between gap-3 mb-2">
                      <h4 className="readout">Hashtags</h4>
                      <CopyButton done={copied === 'hashtags'} onClick={() => handleCopy(genResult.script.hashtags.join(' '), 'hashtags')} what="hashtags" />
                    </div>
                    <ul className="flex flex-wrap gap-1.5">
                      {genResult.script.hashtags.map((tag, i) => (
                        <li key={i} className="text-xs text-ink2 bg-paper3 border border-rule px-2 py-0.5 rounded">{tag}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Cost breakdown */}
                {genResult.cost_estimate && (
                  <div className="tray p-4">
                    <h4 className="text-sm font-semibold text-ink mb-3">Cost breakdown</h4>
                    <dl className="space-y-1.5">
                      {Object.entries(genResult.cost_estimate).filter(([k]) => k !== 'total').map(([k, v]) => (
                        <div key={k} className="flex justify-between gap-3 readout">
                          <dt>{k.replace(/_/g, ' ')}</dt>
                          <dd>${v}</dd>
                        </div>
                      ))}
                      <div className="flex justify-between gap-3 border-t border-rule pt-2 mt-2 font-mono text-sm text-ink">
                        <dt>Total</dt>
                        <dd>${genResult.cost_estimate.total}</dd>
                      </div>
                    </dl>
                  </div>
                )}

                {/* Publish to social media */}
                <section aria-labelledby="ais-publish-title" className="card p-4 sm:p-5 space-y-4">
                  <h3 id="ais-publish-title" className="font-display text-lg text-ink">Publish</h3>

                  {!uploadPostKey ? (
                    <p className="text-sm text-muted">Set your Upload-Post API key in Settings to enable publishing.</p>
                  ) : (
                    <>
                      {/* Platform toggles */}
                      <div role="group" aria-label="Platforms">
                        <SegmentedControl
                          multi
                          size="sm"
                          options={[
                            { value: 'tiktok', label: 'TikTok' },
                            { value: 'instagram', label: 'Instagram' },
                            { value: 'youtube', label: 'YouTube' },
                          ]}
                          value={Object.keys(publishPlatforms).filter((k) => publishPlatforms[k])}
                          onChange={(arr) => setPublishPlatforms({
                            tiktok: arr.includes('tiktok'),
                            instagram: arr.includes('instagram'),
                            youtube: arr.includes('youtube'),
                          })}
                        />
                      </div>

                      {/* Same notice as ResultCard: TikTok lands as a draft,
                          and finding nothing live reads as a failed post. */}
                      {publishPlatforms.tiktok && (
                        <p className="text-xs text-muted leading-relaxed">
                          TikTok arrives as a <b className="text-ink2 font-semibold">draft</b> and you&apos;ll get a
                          notification in the app. Finishing it there lets you add trending sounds
                          and hashtags, which reaches more people than posting from an API.
                        </p>
                      )}

                      {/* Schedule toggle */}
                      <div className="flex flex-wrap items-center gap-3">
                        <label className="flex items-center gap-2 text-sm text-ink2 cursor-pointer min-h-[44px] sm:min-h-0">
                          <input
                            type="checkbox"
                            checked={isScheduling}
                            onChange={(e) => setIsScheduling(e.target.checked)}
                            className="w-4 h-4 accent-[var(--color-accent)]"
                          />
                          <Calendar size={14} className="text-muted" aria-hidden="true" /> Schedule for later
                        </label>
                        {isScheduling && (
                          <>
                            <label htmlFor="ais-schedule-date" className="sr-only">Publish date and time</label>
                            <input
                              id="ais-schedule-date"
                              type="datetime-local"
                              value={scheduleDate}
                              onChange={(e) => setScheduleDate(e.target.value)}
                              className="input-field text-sm py-2 px-3 w-full sm:w-auto"
                            />
                          </>
                        )}
                      </div>

                      {/* Publish button */}
                      <button
                        type="button"
                        onClick={async () => {
                          const selected = Object.keys(publishPlatforms).filter(k => publishPlatforms[k]);
                          if (selected.length === 0) { setPublishResult({ ok: false, msg: 'Select at least one platform' }); return; }
                          if (isScheduling && !scheduleDate) { setPublishResult({ ok: false, msg: 'Select a date' }); return; }

                          setPublishing(true);
                          setPublishResult(null);
                          try {
                            const payload = {
                              job_id: jobId,
                              api_key: uploadPostKey,
                              user_id: uploadUserId,
                              platforms: selected,
                              title: genResult.script?.title,
                              description: genResult.script?.caption || genResult.script?.full_narration,
                            };
                            if (isScheduling && scheduleDate) {
                              payload.scheduled_date = new Date(scheduleDate).toISOString();
                              payload.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
                            }
                            const res = await apiFetch('/api/saasshorts/post', {
                              method: 'POST',
                              headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify(payload),
                            });
                            if (!res.ok) {
                              const err = await res.json().catch(() => ({ detail: 'Failed' }));
                              throw new Error(err.detail || 'Failed');
                            }
                            setPublishResult({ ok: true, msg: isScheduling ? 'Scheduled!' : 'Published!' });
                          } catch (e) {
                            setPublishResult({ ok: false, msg: e.message });
                          } finally {
                            setPublishing(false);
                          }
                        }}
                        disabled={publishing}
                        className="btn-primary w-full"
                      >
                        {publishing ? (
                          <><Loader2 size={16} className="animate-spin" aria-hidden="true" /> {isScheduling ? 'Scheduling…' : 'Publishing…'}</>
                        ) : (
                          <><Share2 size={16} aria-hidden="true" /> {isScheduling ? 'Schedule post' : 'Publish now'}</>
                        )}
                      </button>

                      <div aria-live="polite">
                        {publishResult && (
                          <p className={`text-sm flex items-center gap-1.5 ${publishResult.ok ? 'text-ok' : 'text-danger'}`}>
                            {publishResult.ok
                              ? <Check size={14} aria-hidden="true" />
                              : <AlertCircle size={14} aria-hidden="true" />}
                            {publishResult.msg}
                          </p>
                        )}
                      </div>
                    </>
                  )}
                </section>
              </div>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

// ─── Presentational helpers ───────────────────────────────────────

const STATUS_WORD = { processing: 'Processing', completed: 'Completed', failed: 'Failed', idle: 'Stopped' };

// A neutral mono tag (colour is reserved for the signal).
const TAG = 'readout inline-flex items-center rounded border border-rule2 px-1.5 py-0.5';

// A choice tile: monochrome at rest, the signal edge + wash when selected.
const choiceCard = (active) => `card card-hover relative block w-full text-left ${active ? 'border-vermilion bg-vermilionsoft' : ''}`;

function StepHeading({ id, eyebrow, title, children }) {
  return (
    <header className="mb-6 sm:mb-8">
      <p className="eyebrow mb-2">{eyebrow}</p>
      <h2 id={id} className="page-title break-words">{title}</h2>
      {children && <p className="page-lede mt-3">{children}</p>}
    </header>
  );
}

function SubHeading({ id, title, hint }) {
  return (
    <div>
      <h3 id={id} className="font-display text-lg text-ink">{title}</h3>
      {hint && <p className="text-sm text-muted mt-1">{hint}</p>}
    </div>
  );
}

function ChoiceMark({ active, small = false }) {
  const pos = small ? 'top-2.5 right-2.5 w-5 h-5' : 'top-3.5 right-3.5 w-6 h-6';
  return (
    <span
      aria-hidden="true"
      className={`absolute ${pos} rounded-full border flex items-center justify-center transition-colors duration-200 ${
        active ? 'bg-vermilion border-vermilion text-brassink' : 'bg-paper2 border-rule2'
      }`}
    >
      {active && <Check size={small ? 12 : 14} strokeWidth={2.5} />}
    </span>
  );
}

function ImageCheck() {
  return (
    <span aria-hidden="true" className="absolute top-1.5 right-1.5 w-5 h-5 rounded-full bg-vermilion text-brassink flex items-center justify-center">
      <Check size={12} strokeWidth={2.5} />
    </span>
  );
}

function CopyButton({ done, onClick, what }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="btn-quiet text-xs px-2.5 py-1.5"
    >
      {done ? <Check size={14} className="text-ok" aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
      <span aria-live="polite">{done ? 'Copied' : 'Copy'}<span className="sr-only"> the {what}</span></span>
    </button>
  );
}
