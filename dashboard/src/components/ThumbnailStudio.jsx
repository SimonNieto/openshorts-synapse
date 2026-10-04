import { useState, useRef, useCallback, useEffect } from 'react';
import { Upload, Image, Loader2, Send, Check, Download, ArrowRight, ArrowLeft, Sparkles, Video, Type, X, Plus, MessageSquare, FileText, Youtube, AlertCircle, Settings } from 'lucide-react';
import { getApiUrl } from '../config';
import { apiFetch } from '../lib/api';
import StepIndicator from './ui/StepIndicator';
import SegmentedControl from './ui/SegmentedControl';

const STEPS = ['Source', 'Title', 'Thumbnail', 'Description', 'Publish'];

// Small icon buttons grow to the 44px touch floor on coarse pointers (design.md).
const TOUCH_TARGET = '[@media(pointer:coarse)]:min-w-[44px] [@media(pointer:coarse)]:min-h-[44px]';

function DragDropZone({ label, accept, onFile, file, onClear, icon }) {
  const Icon = icon;
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef(null);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setIsDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) onFile(f);
  }, [onFile]);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  if (file) {
    return (
      <div className="flex items-center gap-3 rounded-input border border-rule2 bg-paper3 p-2.5">
        {file.type?.startsWith('image/') ? (
          <img src={URL.createObjectURL(file)} className="w-12 h-12 rounded-input object-cover bg-black border border-rule2 shrink-0" alt="" />
        ) : (
          <span className="w-12 h-12 rounded-input bg-paper2 border border-rule flex items-center justify-center shrink-0" aria-hidden="true">
            <Icon size={18} className="text-muted" />
          </span>
        )}
        <div className="flex-1 min-w-0">
          <p className="text-sm text-ink truncate">{file.name}</p>
          <p className="readout mt-0.5">{(file.size / 1024 / 1024).toFixed(1)} MB</p>
        </div>
        <button
          type="button"
          onClick={onClear}
          aria-label={`Remove ${file.name}`}
          className={`w-9 h-9 shrink-0 flex items-center justify-center rounded-input text-muted hover:text-ink hover:bg-paper2 transition-colors ${TOUCH_TARGET}`}
        >
          <X size={16} aria-hidden="true" />
        </button>
      </div>
    );
  }

  return (
    <>
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={() => setIsDragging(false)}
        className={`w-full rounded-input border border-dashed px-4 py-6 text-center transition-colors duration-200 ${isDragging
          ? 'border-ink bg-paper3'
          : 'border-rule2 hover:border-ink hover:bg-paper3'
          }`}
      >
        <Icon size={20} className={`mx-auto mb-2 ${isDragging ? 'text-ink' : 'text-muted'}`} aria-hidden="true" />
        <span className="block text-sm font-medium text-ink">{label}</span>
        <span className="block text-xs text-muted mt-1">Drop it here or click to browse</span>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => e.target.files[0] && onFile(e.target.files[0])}
      />
    </>
  );
}

export default function ThumbnailStudio({ geminiApiKey, uploadPostKey, uploadUserId, managed = false, onCreateClips = null, onOpenSettings = null }) {
  // Managed (hosted plan): Gemini runs server-side via the bearer token, no BYOK key.
  // Only send X-Gemini-Key for self-host BYOK. apiFetch attaches the bearer token.
  const keyHeader = geminiApiKey ? { 'X-Gemini-Key': geminiApiKey } : {};
  const needsKey = !geminiApiKey && !managed;
  // Step management
  const [step, setStep] = useState(0);
  const [mode, setMode] = useState(null); // 'video' or 'manual'

  // Step 1 state
  const [videoFile, setVideoFile] = useState(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);

  // Step 2 state
  const [sessionId, setSessionId] = useState(null);
  const [titles, setTitles] = useState([]);
  const [selectedTitle, setSelectedTitle] = useState('');
  const [manualTitle, setManualTitle] = useState('');
  const [chatInput, setChatInput] = useState('');
  const [chatHistory, setChatHistory] = useState([]);
  const [isRefining, setIsRefining] = useState(false);
  const [recommended, setRecommended] = useState([]); // [{index, reason}]
  const [thumbnailTexts, setThumbnailTexts] = useState([]); // hook text paired with each title

  // Step 3 state
  const [faceImage, setFaceImage] = useState(null);
  const [bgImage, setBgImage] = useState(null);
  const [extraPrompt, setExtraPrompt] = useState('');
  const [thumbnailCount, setThumbnailCount] = useState(3);
  const [burnText, setBurnText] = useState(true); // crisp PIL text vs model-rendered text
  const [frames, setFrames] = useState(null); // null = not fetched yet
  const [framesLoading, setFramesLoading] = useState(false);
  const [selectedFrame, setSelectedFrame] = useState(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generatedThumbnails, setGeneratedThumbnails] = useState([]);

  // Description state
  const [description, setDescription] = useState('');
  const [isDescribing, setIsDescribing] = useState(false);

  // Step 4 (Publish) state
  const [selectedThumbnail, setSelectedThumbnail] = useState(null);
  const [isPublishing, setIsPublishing] = useState(false);
  const [publishResult, setPublishResult] = useState(null);

  // Background preprocessing state
  const [preprocessSessionId, setPreprocessSessionId] = useState(null);
  const [isPreprocessing, setIsPreprocessing] = useState(false);

  const chatEndRef = useRef(null);

  const scrollToBottom = () => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  // --- Background Pre-upload (starts Whisper immediately) ---
  const handlePreUpload = async (file) => {
    setPreprocessSessionId(null);
    setIsPreprocessing(true);
    try {
      const formData = new FormData();
      formData.append('file', file);

      const res = await apiFetch('/api/thumbnail/upload', {
        method: 'POST',
        body: formData
      });

      if (res.ok) {
        const data = await res.json();
        setPreprocessSessionId(data.session_id);
        console.log(`🎙️ Background Whisper started: ${data.session_id}`);
      }
    } catch (e) {
      console.error('Pre-upload failed:', e);
    } finally {
      setIsPreprocessing(false);
    }
  };

  // --- Step 1: Analyze Video ---
  const handleAnalyze = async () => {
    if (needsKey) return alert('Please set your Gemini API key in Settings first.');
    setIsAnalyzing(true);

    try {
      const formData = new FormData();

      if (preprocessSessionId) {
        // Use pre-uploaded session (Whisper already running/done in background)
        formData.append('session_id', preprocessSessionId);
      } else if (videoFile) {
        formData.append('file', videoFile);
      } else {
        return alert('Please upload a video file.');
      }

      const res = await apiFetch('/api/thumbnail/analyze', {
        method: 'POST',
        headers: keyHeader,
        body: formData
      });

      if (!res.ok) {
        const err = await res.text();
        throw new Error(err);
      }

      const data = await res.json();
      setSessionId(data.session_id);
      setTitles(data.titles || []);
      setThumbnailTexts(data.thumbnail_texts || []);
      setRecommended(data.recommended || []);
      setChatHistory([{
        role: 'assistant',
        content: `Here are 10 viral title suggestions based on your video. Titles marked TOP PICK are my top picks. Click one to select it, or tell me how to refine them.`
      }]);
      setStep(1);
    } catch (e) {
      alert(`Analysis failed: ${e.message}`);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleManualMode = () => {
    setMode('manual');
    setStep(1);
  };

  // --- Step 2: Title Selection / Refinement ---
  const handleSelectTitle = (title) => {
    setSelectedTitle(title);
  };

  const handleConfirmTitle = () => {
    if (mode === 'manual' && manualTitle) {
      setSelectedTitle(manualTitle);
      // Create session for manual mode
      const newSessionId = sessionId || crypto.randomUUID();
      setSessionId(newSessionId);
      apiFetch('/api/thumbnail/titles', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...keyHeader
        },
        body: JSON.stringify({ title: manualTitle, session_id: newSessionId })
      }).catch(() => { });
    }
    if (selectedTitle || (mode === 'manual' && manualTitle)) {
      setStep(2);
    }
  };

  const handleRefine = async () => {
    if (!chatInput.trim() || !sessionId) return;
    setIsRefining(true);

    const userMsg = chatInput.trim();
    setChatInput('');
    setChatHistory(prev => [...prev, { role: 'user', content: userMsg }]);

    try {
      const res = await apiFetch('/api/thumbnail/titles', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...keyHeader
        },
        body: JSON.stringify({ session_id: sessionId, message: userMsg })
      });

      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setTitles(data.titles || []);
      setThumbnailTexts(data.thumbnail_texts || []);
      setRecommended([]);
      setChatHistory(prev => [...prev, {
        role: 'assistant',
        content: `Here are refined titles based on your feedback. Click one to select it.`
      }]);
      setTimeout(scrollToBottom, 100);
    } catch (e) {
      setChatHistory(prev => [...prev, {
        role: 'assistant',
        content: `Failed to refine: ${e.message}`
      }]);
    } finally {
      setIsRefining(false);
    }
  };

  // --- Step 3: Generate Thumbnails ---
  const handleGenerate = async () => {
    if (needsKey) return alert('Please set your Gemini API key in Settings first.');
    const finalTitle = selectedTitle || manualTitle;
    if (!finalTitle) return alert('Please select or enter a title first.');

    setIsGenerating(true);
    setGeneratedThumbnails([]);

    try {
      const formData = new FormData();
      formData.append('session_id', sessionId || 'manual');
      formData.append('title', finalTitle);
      formData.append('extra_prompt', extraPrompt);
      formData.append('count', thumbnailCount);
      formData.append('burn_text', burnText ? 'true' : 'false');
      if (selectedFrame && !faceImage) formData.append('frame', selectedFrame);
      if (faceImage) formData.append('face', faceImage);
      if (bgImage) formData.append('background', bgImage);

      const res = await apiFetch('/api/thumbnail/generate', {
        method: 'POST',
        headers: keyHeader,
        body: formData
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => null);
        throw new Error(errData?.detail || `Server error ${res.status}`);
      }

      const data = await res.json();
      if (!data.thumbnails || data.thumbnails.length === 0) {
        throw new Error('No thumbnails were generated. Your Gemini API key may not have access to image generation.');
      }
      setGeneratedThumbnails(data.thumbnails);
    } catch (e) {
      alert(`Generation failed: ${e.message}`);
    } finally {
      setIsGenerating(false);
    }
  };

  // Frames with a big, sharp face from the uploaded video: one click replaces
  // the face upload nobody makes. Fetched once when the generate step opens.
  // `frames` is deliberately not a dependency: setting it inside the effect
  // would re-run it and the cleanup would discard the response in flight.
  const framesRequestedFor = useRef(null);
  useEffect(() => {
    if (step !== 2 || mode !== 'video' || !sessionId) return;
    if (framesRequestedFor.current === sessionId) return;
    framesRequestedFor.current = sessionId;
    setFrames([]);
    setFramesLoading(true);
    apiFetch(`/api/thumbnail/frames/${sessionId}`)
      .then(res => (res.ok ? res.json() : { frames: [] }))
      .then(data => setFrames(data.frames || []))
      .catch(() => setFrames([]))
      .finally(() => setFramesLoading(false));
  }, [step, mode, sessionId]);

  const handleDownload = async (url) => {
    try {
      const response = await fetch(getApiUrl(url));
      const blob = await response.blob();
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = url.split('/').pop() || 'thumbnail.png';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(blobUrl);
    } catch {
      // Fallback: open in new tab if fetch fails
      window.open(getApiUrl(url), '_blank');
    }
  };

  // --- Description Generation ---
  const handleGenerateDescription = async () => {
    if (needsKey) return alert('Please set your Gemini API key in Settings first.');
    const finalTitle = selectedTitle || manualTitle;
    if (!finalTitle) return alert('Please select a title first.');
    if (!sessionId) return alert('No session available.');

    setIsDescribing(true);
    try {
      const res = await apiFetch('/api/thumbnail/describe', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...keyHeader
        },
        body: JSON.stringify({ session_id: sessionId, title: finalTitle })
      });

      if (!res.ok) {
        const err = await res.text();
        throw new Error(err);
      }

      const data = await res.json();
      setDescription(data.description || '');
    } catch (e) {
      alert(`Description generation failed: ${e.message}`);
    } finally {
      setIsDescribing(false);
    }
  };

  // --- Publish to YouTube ---
  const handlePublish = async () => {
    if (!managed && (!uploadPostKey || !uploadUserId)) return alert('Please configure your Upload-Post API key and user in Settings first.');
    const finalTitle = selectedTitle || manualTitle;
    if (!finalTitle) return alert('No title selected.');
    if (!selectedThumbnail) return alert('Please select a thumbnail first.');
    if (!description) return alert('Please generate or write a description first.');

    setIsPublishing(true);
    setPublishResult(null);
    try {
      const formData = new FormData();
      formData.append('session_id', sessionId);
      formData.append('title', finalTitle);
      formData.append('description', description);
      formData.append('thumbnail_url', selectedThumbnail);
      formData.append('api_key', uploadPostKey);
      formData.append('user_id', uploadUserId);

      // Submit the publish job — returns immediately with a publish_id
      const res = await apiFetch('/api/thumbnail/publish', {
        method: 'POST',
        body: formData
      });

      if (!res.ok) {
        const err = await res.text();
        throw new Error(err);
      }

      const { publish_id } = await res.json();

      // Poll for status every 2 seconds (upload can take minutes for large videos)
      await new Promise((resolve, reject) => {
        const interval = setInterval(async () => {
          try {
            const statusRes = await fetch(getApiUrl(`/api/thumbnail/publish/status/${publish_id}`));
            if (!statusRes.ok) { clearInterval(interval); reject(new Error('Status check failed')); return; }
            const statusData = await statusRes.json();

            if (statusData.status === 'done') {
              clearInterval(interval);
              setPublishResult({ success: true, data: statusData.result });
              resolve();
            } else if (statusData.status === 'failed') {
              clearInterval(interval);
              reject(new Error(statusData.error || 'Upload failed'));
            }
            // 'uploading' → keep polling
          } catch (e) {
            clearInterval(interval);
            reject(e);
          }
        }, 2000);
      });

    } catch (e) {
      setPublishResult({ success: false, error: e.message });
    } finally {
      setIsPublishing(false);
    }
  };

  const handleReset = () => {
    setStep(0);
    setMode(null);
    setVideoFile(null);
    setSessionId(null);
    setTitles([]);
    setSelectedTitle('');
    setManualTitle('');
    setChatInput('');
    setChatHistory([]);
    setFaceImage(null);
    setFrames(null);
    framesRequestedFor.current = null;
    setSelectedFrame(null);
    setThumbnailTexts([]);
    setBgImage(null);
    setExtraPrompt('');
    setGeneratedThumbnails([]);
    setDescription('');
    setIsDescribing(false);
    setSelectedThumbnail(null);
    setIsPublishing(false);
    setPublishResult(null);
    setPreprocessSessionId(null);
    setIsPreprocessing(false);
    setRecommended([]);
  };

  // --- Presentation only (copy + derived status; no state of its own) ---
  const stepHeads = [
    {
      kicker: 'New project',
      title: 'Start from a video or a title',
      lede: 'Upload the video to get title ideas drawn from what is said in it, or write your own title and go straight to thumbnails.',
    },
    {
      kicker: 'Title',
      title: 'Choose the title',
      lede: mode === 'manual'
        ? 'Check the title that will sit next to your thumbnail in the feed.'
        : 'Title ideas drawn from your video. Pick one, or send notes for another round.',
    },
    {
      kicker: 'Thumbnail',
      title: 'Design the thumbnail',
      lede: 'Brief the image model, then pick the thumbnail that wins the click.',
    },
    {
      kicker: 'Description',
      title: 'Write the description',
      lede: mode === 'video'
        ? 'Generate a description with chapter timestamps from the transcript, then edit it freely.'
        : 'Write the description that runs under the video.',
    },
    {
      kicker: 'Publish',
      title: 'Publish to YouTube',
      lede: 'A last read of the title, thumbnail and description before the video goes to your channel.',
    },
  ];
  const head = stepHeads[step];

  // One polite announcement for whatever is running right now.
  const liveStatus = isAnalyzing ? 'Analyzing the video…'
    : isRefining ? 'Refining titles…'
      : isGenerating ? 'Generating thumbnails. This may take a minute per thumbnail.'
        : isDescribing ? 'Writing the description…'
          : isPublishing ? 'Publishing to YouTube…'
            : (step === 2 && generatedThumbnails.length > 0) ? `${generatedThumbnails.length} thumbnail${generatedThumbnails.length === 1 ? '' : 's'} ready. Select one to continue.`
              : (step === 4 && publishResult?.success) ? 'Published successfully.'
                : '';

  return (
    <div className="h-full overflow-y-auto custom-scrollbar animate-fade">
      <div className="max-w-6xl mx-auto p-4 sm:p-8 space-y-8">
        <p className="sr-only" aria-live="polite">{liveStatus}</p>

        {/* Masthead: the step's headline, what it is for, and a way out */}
        <header className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
          <div className="min-w-0">
            <p className="eyebrow mb-2">{head.kicker}</p>
            <h2 className="page-title">{head.title}</h2>
            <p className="page-lede mt-2">{head.lede}</p>
          </div>
          {step > 0 && (
            <button type="button" onClick={handleReset} className="btn-quiet self-start sm:self-end shrink-0">
              <Plus size={14} aria-hidden="true" />
              New project
            </button>
          )}
        </header>

        <div className="border-y border-rule py-4">
          <StepIndicator steps={STEPS} current={step} />
        </div>

        {/* Gemini API Key Warning (self-host BYOK only; managed uses server key) */}
        {needsKey && (
          <div className="flex items-start gap-3 rounded-card border border-warn/40 bg-warn/10 p-4 sm:p-5">
            <AlertCircle size={18} className="text-warn shrink-0 mt-0.5" aria-hidden="true" />
            <div>
              <p className="text-sm font-semibold text-ink">Gemini API key required</p>
              <p className="text-sm text-ink2 mt-1">
                YouTube Studio needs a Google Gemini API key. Add it in <strong className="font-semibold text-ink">Settings</strong> before
                you start. Gemini's free tier includes 1,500 requests per day.
              </p>
            </div>
          </div>
        )}

        {/* ===== STEP 0: Input Mode Selection ===== */}
        {step === 0 && (
          <div
            className={`grid lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] gap-6 lg:gap-8 ${needsKey ? 'opacity-50 pointer-events-none select-none' : ''}`}
            inert={needsKey ? '' : undefined}
          >
            {/* Mode A: Video Analysis */}
            <section aria-labelledby="ts-video-heading" className="card-print p-5 sm:p-7 flex flex-col gap-5">
              <div className="flex items-start gap-3">
                <span className="w-10 h-10 rounded-input bg-paper3 border border-rule flex items-center justify-center shrink-0" aria-hidden="true">
                  <Video size={18} className="text-ink" />
                </span>
                <div className="min-w-0">
                  <h3 id="ts-video-heading" className="font-display text-xl text-ink leading-tight">From your video</h3>
                  <p className="text-sm text-muted mt-1">AI reads the transcript and suggests titles that match what is actually said.</p>
                </div>
              </div>

              <DragDropZone
                label="Choose a video file"
                accept="video/*"
                onFile={(f) => { setVideoFile(f); setMode('video'); handlePreUpload(f); }}
                file={videoFile}
                onClear={() => { setVideoFile(null); setPreprocessSessionId(null); }}
                icon={Video}
              />

              <div aria-live="polite">
                {isPreprocessing && (
                  <p className="flex items-center gap-2 text-sm text-ink2 tray px-3 py-2.5">
                    <Loader2 size={14} className="animate-spin text-muted shrink-0" aria-hidden="true" />
                    Pre-processing the video (Whisper transcription starting)…
                  </p>
                )}
                {preprocessSessionId && !isPreprocessing && (
                  <p className="flex items-center gap-2 text-sm text-ink2 tray px-3 py-2.5">
                    <Check size={14} className="text-ok shrink-0" aria-hidden="true" />
                    Video uploaded. Transcription is running in the background.
                  </p>
                )}
              </div>

              <div className="mt-auto">
                <button
                  type="button"
                  onClick={handleAnalyze}
                  disabled={isAnalyzing || !videoFile}
                  className="w-full btn-accent"
                >
                  {isAnalyzing ? (
                    <>
                      <Loader2 size={16} className="animate-spin" aria-hidden="true" />
                      Analyzing video…
                    </>
                  ) : (
                    <>
                      <Sparkles size={16} aria-hidden="true" />
                      Analyze and suggest titles
                    </>
                  )}
                </button>
              </div>
            </section>

            {/* Mode B: Manual Title */}
            <section aria-labelledby="ts-manual-heading" className="card p-5 sm:p-7 flex flex-col gap-5">
              <div className="flex items-start gap-3">
                <span className="w-10 h-10 rounded-input bg-paper3 border border-rule flex items-center justify-center shrink-0" aria-hidden="true">
                  <Type size={18} className="text-muted" />
                </span>
                <div className="min-w-0">
                  <h3 id="ts-manual-heading" className="font-display text-xl text-ink leading-tight">Write your own</h3>
                  <p className="text-sm text-muted mt-1">Skip the analysis and go straight to thumbnails with a title you already have.</p>
                </div>
              </div>

              <div>
                <label htmlFor="ts-manual-input" className="block text-sm font-medium text-ink mb-2">YouTube title</label>
                <input
                  id="ts-manual-input"
                  type="text"
                  value={manualTitle}
                  onChange={(e) => setManualTitle(e.target.value)}
                  placeholder="Enter your YouTube title…"
                  className="input-field"
                  maxLength={70}
                  aria-describedby="ts-manual-count"
                />
                <p id="ts-manual-count" className="readout mt-2 text-right">{manualTitle.length} / 70</p>
              </div>

              <div className="mt-auto">
                <button
                  type="button"
                  onClick={handleManualMode}
                  disabled={!manualTitle.trim()}
                  className="w-full btn-ghost"
                >
                  Use this title
                  <ArrowRight size={16} aria-hidden="true" />
                </button>
              </div>
            </section>
          </div>
        )}

        {/* ===== STEP 1: Title Selection ===== */}
        {step === 1 && (
          <div className={`grid gap-6 lg:gap-8 items-start ${mode === 'manual' ? 'max-w-2xl' : 'lg:grid-cols-[minmax(0,1fr)_minmax(18rem,22rem)]'}`}>
            {/* Titles */}
            <div className="min-w-0 space-y-4">
              {selectedTitle && (
                <div className="sticky top-2 z-10 card-print p-3 sm:p-4 flex items-center gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="readout flex items-center gap-1.5">
                      <Check size={12} className="text-ink" aria-hidden="true" />
                      Selected
                    </p>
                    <p className="font-display text-base sm:text-lg text-ink leading-snug mt-0.5 line-clamp-2 break-words">{selectedTitle}</p>
                  </div>
                  {mode !== 'manual' && selectedTitle && (
                    <button
                      type="button"
                      onClick={handleConfirmTitle}
                      className="btn-accent shrink-0"
                    >
                      <span>Use <span className="hidden sm:inline">this </span>title</span>
                      <ArrowRight size={16} aria-hidden="true" />
                    </button>
                  )}
                </div>
              )}

              {titles.length > 0 && (
                <section aria-labelledby="ts-titles-heading">
                  <div className="flex items-baseline justify-between gap-3 border-b border-rule2 pb-3">
                    <h3 id="ts-titles-heading" className="font-display text-lg text-ink">Suggested titles</h3>
                    <p className="readout">{titles.length} titles</p>
                  </div>
                  <ol className="divide-y divide-rule">
                    {titles.map((title, i) => {
                      const rec = recommended.find(r => r.index === i);
                      const recRank = recommended.findIndex(r => r.index === i);
                      const isSelected = selectedTitle === title;
                      return (
                        <li key={i}>
                          <button
                            type="button"
                            onClick={() => handleSelectTitle(title)}
                            aria-pressed={isSelected}
                            className={`w-full text-left grid grid-cols-[1.75rem_minmax(0,1fr)] gap-3 sm:gap-4 px-2 sm:px-3 py-4 border-l-2 transition-colors duration-200 ${isSelected
                              ? 'bg-paper3 border-ink'
                              : 'border-transparent hover:bg-paper2'
                              }`}
                          >
                            <span className={`font-mono text-xs pt-1 ${isSelected ? 'text-ink' : 'text-muted'}`} aria-hidden="true">
                              {isSelected ? <Check size={14} /> : String(i + 1).padStart(2, '0')}
                            </span>
                            <span className="min-w-0">
                              {rec && (
                                <span className="readout block mb-1 !text-ink2">{recRank === 0 ? 'Top pick' : 'Second pick'}</span>
                              )}
                              <span className="block font-display text-[1.05rem] sm:text-xl leading-snug text-ink break-words">{title}</span>
                              {rec && (
                                <span className="block text-sm text-muted mt-1.5 leading-relaxed">{rec.reason}</span>
                              )}
                              <span className="flex flex-wrap items-baseline gap-x-4 gap-y-1 mt-2">
                                <span className="readout">{title.length} chars</span>
                                {thumbnailTexts[i] && (
                                  <span className="readout">
                                    Thumbnail text{' '}
                                    <span className="normal-case tracking-normal font-body text-xs text-ink2">“{thumbnailTexts[i]}”</span>
                                  </span>
                                )}
                              </span>
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ol>
                </section>
              )}

              {mode !== 'manual' && !selectedTitle && titles.length > 0 && (
                <p className="text-sm text-muted">Pick a title to continue.</p>
              )}

              {isRefining && (
                <p className="flex items-center justify-center gap-2 py-6 text-sm text-ink2">
                  <Loader2 size={16} className="animate-spin text-muted" aria-hidden="true" />
                  Refining titles…
                </p>
              )}
            </div>

            {/* Controls: your own title, or the refinement chat */}
            <div className="flex flex-col gap-4 min-w-0 lg:sticky lg:top-2">
              {mode === 'manual' ? (
                <section aria-labelledby="ts-own-heading" className="card p-5 sm:p-6 space-y-4">
                  <h3 id="ts-own-heading" className="font-display text-lg text-ink">Your title</h3>
                  <div>
                    <label htmlFor="ts-own-input" className="sr-only">YouTube title</label>
                    <input
                      id="ts-own-input"
                      type="text"
                      value={manualTitle}
                      onChange={(e) => setManualTitle(e.target.value)}
                      className="input-field"
                      maxLength={70}
                      aria-describedby="ts-own-count"
                    />
                    <p id="ts-own-count" className="readout mt-2 text-right">{manualTitle.length} / 70</p>
                  </div>
                  <button
                    type="button"
                    onClick={handleConfirmTitle}
                    disabled={!manualTitle.trim()}
                    className="w-full btn-accent"
                  >
                    Continue to thumbnails
                    <ArrowRight size={16} aria-hidden="true" />
                  </button>
                </section>
              ) : (
                <section aria-labelledby="ts-chat-heading" className="card flex flex-col h-[440px] lg:h-[540px]">
                  <div className="flex items-center gap-2 px-4 py-3 border-b border-rule">
                    <MessageSquare size={16} className="text-muted" aria-hidden="true" />
                    <h3 id="ts-chat-heading" className="font-display text-base text-ink">Refine with notes</h3>
                  </div>

                  {/* Chat messages */}
                  <div
                    className="flex-1 overflow-y-auto custom-scrollbar px-4 py-4 space-y-3"
                    role="log"
                    aria-live="polite"
                    aria-labelledby="ts-chat-heading"
                  >
                    {chatHistory.map((msg, i) => (
                      <div key={i} className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
                        <span className="readout mb-1">{msg.role === 'user' ? 'You' : 'Assistant'}</span>
                        <p className={`max-w-[92%] px-3 py-2 rounded-card text-sm leading-relaxed break-words ${msg.role === 'user'
                          ? 'bg-paper3 text-ink'
                          : 'border border-rule text-ink2'
                          }`}>
                          {msg.content}
                        </p>
                      </div>
                    ))}
                    <div ref={chatEndRef} />
                  </div>

                  {/* Chat input */}
                  <div className="flex gap-2 p-3 border-t border-rule">
                    <label htmlFor="ts-chat-input" className="sr-only">Notes for the next round of titles</label>
                    <input
                      id="ts-chat-input"
                      type="text"
                      value={chatInput}
                      onChange={(e) => setChatInput(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleRefine()}
                      placeholder="e.g. Shorter, more curiosity…"
                      className="input-field flex-1 min-w-0"
                      disabled={isRefining}
                    />
                    <button
                      type="button"
                      onClick={handleRefine}
                      disabled={isRefining || !chatInput.trim()}
                      className="btn-ghost px-3.5 shrink-0"
                      aria-label="Send notes"
                    >
                      {isRefining ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <Send size={16} aria-hidden="true" />}
                    </button>
                  </div>
                </section>
              )}
            </div>
          </div>
        )}

        {/* ===== STEP 2: Thumbnail Generation ===== */}
        {step === 2 && (
          <div className="grid lg:grid-cols-[minmax(17rem,22rem)_minmax(0,1fr)] gap-6 lg:gap-10 items-start">
            {/* The brief */}
            <div className="space-y-4 min-w-0">
              <section aria-labelledby="ts-brief-title" className="card p-5 space-y-3">
                <h3 id="ts-brief-title" className="readout">Title</h3>
                <p className="font-display text-lg text-ink leading-snug break-words">{selectedTitle || manualTitle}</p>
                <button
                  type="button"
                  onClick={() => setStep(1)}
                  className="btn-quiet"
                >
                  <ArrowLeft size={14} aria-hidden="true" /> Change title
                </button>
              </section>

              {mode === 'video' && frames !== null && (
                <section aria-labelledby="ts-frames-heading" className="card p-5 space-y-3">
                  <h3 id="ts-frames-heading" className="font-display text-base text-ink">Your face from the video</h3>
                  {frames.length === 0 ? (
                    <p className="text-sm text-muted">{framesLoading ? 'Looking for sharp frames with a face…' : 'No usable face found in the video.'}</p>
                  ) : (
                    <>
                      <ul className="grid grid-cols-3 gap-2">
                        {frames.map((f) => {
                          const at = `${Math.floor(f.time / 60)}:${String(Math.floor(f.time % 60)).padStart(2, '0')}`;
                          const isPicked = selectedFrame === f.url;
                          return (
                            <li key={f.url}>
                              <button
                                type="button"
                                onClick={() => setSelectedFrame(selectedFrame === f.url ? null : f.url)}
                                aria-pressed={isPicked}
                                aria-label={`Frame at ${at}`}
                                className={`relative block w-full rounded-input overflow-hidden bg-black border transition-colors ${isPicked ? 'border-ink' : 'border-rule2 hover:border-ink'}`}
                              >
                                <img src={getApiUrl(f.url)} alt="" className="w-full aspect-video object-cover" />
                                <span className="absolute bottom-1 right-1 font-mono text-[10.5px] leading-none text-ink bg-paper/85 px-1 py-0.5 rounded-[4px]" aria-hidden="true">
                                  {at}
                                </span>
                                {isPicked && (
                                  <span className="absolute top-1 left-1 w-5 h-5 rounded-full bg-ink text-paper flex items-center justify-center" aria-hidden="true">
                                    <Check size={12} />
                                  </span>
                                )}
                              </button>
                            </li>
                          );
                        })}
                      </ul>
                      <p className="text-xs text-muted">
                        {selectedFrame ? 'This frame is the person reference (a photo upload below overrides it).' : 'Pick a frame so the thumbnail shows you, not a stranger.'}
                      </p>
                    </>
                  )}
                </section>
              )}

              <section aria-labelledby="ts-refs-heading" className="card p-5 space-y-4">
                <div>
                  <h3 id="ts-refs-heading" className="font-display text-base text-ink">Reference images</h3>
                  <p className="text-xs text-muted mt-1">Both optional.</p>
                </div>
                <DragDropZone
                  label="Face or person photo"
                  accept="image/*"
                  onFile={setFaceImage}
                  file={faceImage}
                  onClear={() => setFaceImage(null)}
                  icon={Upload}
                />
                <DragDropZone
                  label="Background image"
                  accept="image/*"
                  onFile={setBgImage}
                  file={bgImage}
                  onClear={() => setBgImage(null)}
                  icon={Image}
                />
              </section>

              <div className="card p-5 space-y-2">
                <label htmlFor="ts-extra-prompt" className="flex items-baseline justify-between gap-2">
                  <span className="font-display text-base text-ink">Instructions</span>
                  <span className="readout">Optional</span>
                </label>
                <textarea
                  id="ts-extra-prompt"
                  value={extraPrompt}
                  onChange={(e) => setExtraPrompt(e.target.value)}
                  placeholder="e.g. Red and black colours, dramatic lighting, money emojis…"
                  className="input-field resize-none h-24"
                />
              </div>

              <section aria-labelledby="ts-output-heading" className="card p-5 space-y-5">
                <h3 id="ts-output-heading" className="sr-only">Output</h3>
                <fieldset className="space-y-2">
                  <legend className="text-sm font-medium text-ink mb-2">Text on the thumbnail</legend>
                  <SegmentedControl
                    options={[{ value: true, label: 'Crisp' }, { value: false, label: 'AI painted' }]}
                    value={burnText}
                    onChange={setBurnText}
                  />
                  <p className="text-xs text-muted">
                    {burnText ? 'Text is set in a bold font after the image is painted: always spelled right.' : 'The image model paints the text itself: more integrated, sometimes misspelled.'}
                  </p>
                </fieldset>

                <fieldset>
                  <legend className="text-sm font-medium text-ink mb-2">How many thumbnails</legend>
                  <SegmentedControl
                    options={[1, 2, 3, 4].map(n => ({ value: n, label: String(n) }))}
                    value={thumbnailCount}
                    onChange={setThumbnailCount}
                    size="sm"
                  />
                </fieldset>
              </section>

              <button
                type="button"
                onClick={handleGenerate}
                disabled={isGenerating}
                className="w-full btn-accent"
              >
                {isGenerating ? (
                  <>
                    <Loader2 size={16} className="animate-spin" aria-hidden="true" />
                    Generating thumbnails…
                  </>
                ) : (
                  <>
                    <Sparkles size={16} aria-hidden="true" />
                    Generate thumbnails
                  </>
                )}
              </button>
            </div>

            {/* The results: framed 16:9 thumbnails on black */}
            <section aria-labelledby="ts-results-heading" className="min-w-0 space-y-5">
              <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-rule2 pb-3">
                <h3 id="ts-results-heading" className="font-display text-xl text-ink">Thumbnails</h3>
                <p className="readout">
                  {generatedThumbnails.length > 0 ? `${generatedThumbnails.length} ready` : `${thumbnailCount} to generate`}
                </p>
              </div>

              {generatedThumbnails.length > 0 ? (
                <div className="space-y-6">
                  <p className="text-sm text-muted">Select the one to publish. Download any of them.</p>
                  <ul className={`grid gap-x-5 gap-y-7 ${generatedThumbnails.length > 1 ? 'sm:grid-cols-2' : ''}`}>
                    {generatedThumbnails.map((thumb, i) => {
                      const url = thumb.url;
                      const isSelected = selectedThumbnail === url;
                      return (
                        <li key={url}>
                          <figure>
                            <div className="relative">
                              <button
                                type="button"
                                onClick={() => setSelectedThumbnail(url)}
                                aria-pressed={isSelected}
                                aria-label={`Select thumbnail ${i + 1}${thumb.text ? `: ${thumb.text}` : ''}`}
                                className={`block w-full rounded-input overflow-hidden bg-black border transition-[border-color,box-shadow] duration-200 ${isSelected
                                  ? 'border-vermilion shadow-print-accent'
                                  : 'border-rule2 hover:border-ink'
                                  }`}
                              >
                                <img
                                  src={getApiUrl(url)}
                                  alt=""
                                  className="w-full aspect-video object-cover"
                                />
                              </button>
                              {isSelected && (
                                <span className="badge-float absolute top-2 left-2 pointer-events-none">
                                  <Check size={12} aria-hidden="true" /> Selected
                                </span>
                              )}
                            </div>
                            <figcaption className="mt-3 flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <p className="readout">Thumbnail {i + 1}</p>
                                {thumb.text && <p className="text-sm font-medium text-ink leading-snug mt-1 break-words">“{thumb.text}”</p>}
                                {thumb.why && <p className="text-xs text-muted mt-1 line-clamp-2">{thumb.why}</p>}
                                {thumb.fallback && (
                                  <p className="text-xs text-ink2 mt-1.5 flex items-start gap-1.5">
                                    <AlertCircle size={14} className="text-warn shrink-0" aria-hidden="true" />
                                    Gemini refused to draw this person (public figures are blocked), so it was rendered without them.
                                  </p>
                                )}
                              </div>
                              <button
                                type="button"
                                onClick={(e) => { e.stopPropagation(); handleDownload(url); }}
                                className="btn-quiet shrink-0"
                                aria-label={`Download thumbnail ${i + 1}`}
                              >
                                <Download size={14} aria-hidden="true" />
                                <span className="hidden sm:inline">Download</span>
                              </button>
                            </figcaption>
                          </figure>
                        </li>
                      );
                    })}
                  </ul>

                  {/* How it reads in the feed on a phone, where the click is decided */}
                  <section aria-labelledby="ts-feed-heading" className="tray p-4 sm:p-5 space-y-4">
                    <div>
                      <h3 id="ts-feed-heading" className="font-display text-base text-ink">In the phone feed</h3>
                      <p className="text-xs text-muted mt-0.5">How each thumbnail reads at feed size, where the click is decided.</p>
                    </div>
                    <ul className="space-y-3">
                      {generatedThumbnails.map((thumb) => (
                        <li key={thumb.url} className="flex gap-3 items-start">
                          <img src={getApiUrl(thumb.url)} alt="" className="w-[140px] sm:w-[168px] aspect-video object-cover rounded-input bg-black border border-rule2 shrink-0" />
                          <div className="min-w-0">
                            <p className="text-sm text-ink font-medium leading-snug line-clamp-2 break-words">{selectedTitle || manualTitle}</p>
                            <p className="text-xs text-muted mt-1">Your channel · 1.2K views · 2 hours ago</p>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </section>

                  <div className="flex flex-col sm:flex-row gap-3">
                    {/* Regenerate */}
                    <button
                      type="button"
                      onClick={handleGenerate}
                      disabled={isGenerating}
                      className="btn-ghost sm:flex-1"
                    >
                      {isGenerating ? (
                        <>
                          <Loader2 size={16} className="animate-spin" aria-hidden="true" />
                          Regenerating…
                        </>
                      ) : (
                        <>
                          <Sparkles size={16} aria-hidden="true" />
                          Regenerate
                        </>
                      )}
                    </button>

                    {/* Proceed to Description */}
                    {selectedThumbnail && (
                      <button
                        type="button"
                        onClick={() => setStep(3)}
                        className="btn-primary sm:flex-1"
                      >
                        Next: description
                        <ArrowRight size={16} aria-hidden="true" />
                      </button>
                    )}
                  </div>
                  {!selectedThumbnail && (
                    <p className="text-sm text-muted">Select a thumbnail to continue.</p>
                  )}
                </div>
              ) : isGenerating ? (
                <div className="space-y-4">
                  <ul className={`grid gap-5 ${thumbnailCount > 1 ? 'sm:grid-cols-2' : ''}`} aria-hidden="true">
                    {Array.from({ length: thumbnailCount }, (_, i) => (
                      <li key={i} className="aspect-video rounded-input bg-paper3 border border-rule2 animate-pulse" />
                    ))}
                  </ul>
                  <p className="flex items-center gap-2 text-sm text-ink2">
                    <Loader2 size={16} className="animate-spin text-muted shrink-0" aria-hidden="true" />
                    Generating thumbnails. This may take a minute per thumbnail.
                  </p>
                </div>
              ) : (
                <div className="space-y-4">
                  <ul className={`grid gap-5 ${thumbnailCount > 1 ? 'sm:grid-cols-2' : ''}`} aria-hidden="true">
                    {Array.from({ length: thumbnailCount }, (_, i) => (
                      <li key={i} className="aspect-video rounded-input border border-dashed border-rule2 flex items-center justify-center">
                        <span className="readout">Thumbnail {i + 1}</span>
                      </li>
                    ))}
                  </ul>
                  <p className="text-sm text-muted">Your thumbnails will appear here. Set the brief, then press Generate thumbnails.</p>
                </div>
              )}
            </section>
          </div>
        )}

        {/* ===== STEP 3: YouTube Description ===== */}
        {step === 3 && (
          <div className="grid lg:grid-cols-[minmax(17rem,22rem)_minmax(0,1fr)] gap-6 lg:gap-10 items-start">
            {/* Context & Controls */}
            <div className="space-y-4 min-w-0">
              <button
                type="button"
                onClick={() => setStep(2)}
                className="btn-quiet"
              >
                <ArrowLeft size={14} aria-hidden="true" /> Back to thumbnails
              </button>

              {/* Selected Thumbnail Preview */}
              {selectedThumbnail && (
                <figure>
                  <img
                    src={getApiUrl(selectedThumbnail)}
                    alt="Selected thumbnail"
                    className="w-full aspect-video object-cover rounded-input bg-black border border-rule2"
                  />
                  <figcaption className="readout mt-2 flex items-center gap-1.5">
                    <Check size={12} className="text-ink" aria-hidden="true" /> Selected thumbnail
                  </figcaption>
                </figure>
              )}

              {/* Title */}
              <section aria-labelledby="ts-desc-title" className="card p-5 space-y-2">
                <h3 id="ts-desc-title" className="readout">Title</h3>
                <p className="font-display text-lg text-ink leading-snug break-words">{selectedTitle || manualTitle}</p>
              </section>

              {/* Generate Description Button */}
              {mode === 'video' && (
                <section aria-labelledby="ts-ai-desc-heading" className="card p-5 space-y-3">
                  <div className="flex items-center justify-between gap-2">
                    <h3 id="ts-ai-desc-heading" className="font-display text-base text-ink flex items-center gap-2">
                      <Sparkles size={16} className="text-muted" aria-hidden="true" />
                      AI description
                    </h3>
                    <span className="readout">With chapters</span>
                  </div>
                  <p className="text-sm text-muted">
                    Written from your video transcript, with chapter timestamps.
                  </p>
                  <button
                    type="button"
                    onClick={handleGenerateDescription}
                    disabled={isDescribing}
                    className={`w-full ${description ? 'btn-ghost' : 'btn-accent'}`}
                  >
                    {isDescribing ? (
                      <>
                        <Loader2 size={16} className="animate-spin" aria-hidden="true" />
                        Generating description…
                      </>
                    ) : (
                      <>
                        <FileText size={16} aria-hidden="true" />
                        {description ? 'Regenerate description' : 'Generate description'}
                      </>
                    )}
                  </button>
                </section>
              )}
            </div>

            {/* Editable Description */}
            <section aria-labelledby="ts-desc-label" className="card-print p-5 sm:p-6 flex flex-col gap-3 min-w-0">
              <div className="flex items-center justify-between gap-3">
                <label id="ts-desc-label" htmlFor="ts-desc" className="font-display text-lg text-ink">YouTube description</label>
                <span id="ts-desc-count" className="readout">{description.length} / 5000</span>
              </div>

              <textarea
                id="ts-desc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder={mode === 'video'
                  ? "Press 'Generate description' to write one with chapters, or write your own…"
                  : "Write your YouTube video description here…"
                }
                className="input-field resize-y min-h-[320px] lg:min-h-[480px] leading-relaxed custom-scrollbar"
                maxLength={5000}
                aria-describedby={description ? 'ts-desc-count' : 'ts-desc-count ts-desc-help'}
              />

              {!description && (
                <p id="ts-desc-help" className="text-sm text-muted">
                  {mode === 'video'
                    ? "AI writes a description with chapter timestamps from your video's Whisper transcript."
                    : "Write a description for your YouTube video. You can go on to publish once it has one."}
                </p>
              )}

              {/* Next: Publish */}
              {description && (
                <div className="flex justify-end pt-1">
                  <button
                    type="button"
                    onClick={() => setStep(4)}
                    className="btn-accent w-full sm:w-auto"
                  >
                    Next: publish
                    <ArrowRight size={16} aria-hidden="true" />
                  </button>
                </div>
              )}
            </section>
          </div>
        )}

        {/* ===== STEP 4: Publish to YouTube ===== */}
        {step === 4 && (
          <div className="grid lg:grid-cols-[minmax(0,1fr)_minmax(17rem,21rem)] gap-6 lg:gap-10 items-start">
            {/* The final read: thumbnail, title, description */}
            <section aria-labelledby="ts-proof-heading" className="card p-5 sm:p-6 space-y-5 min-w-0">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h3 id="ts-proof-heading" className="font-display text-lg text-ink">Final read</h3>
                <button
                  type="button"
                  onClick={() => setStep(3)}
                  className="btn-quiet"
                >
                  <ArrowLeft size={14} aria-hidden="true" /> Back to description
                </button>
              </div>

              {/* Selected Thumbnail Preview */}
              {selectedThumbnail && (
                <figure>
                  <img
                    src={getApiUrl(selectedThumbnail)}
                    alt="Selected thumbnail"
                    className="w-full aspect-video object-cover rounded-input bg-black border border-rule2"
                  />
                  <figcaption className="readout mt-2 flex items-center gap-1.5">
                    <Check size={12} className="text-ink" aria-hidden="true" /> Selected thumbnail
                  </figcaption>
                </figure>
              )}

              {/* Editable Title */}
              <div>
                <label htmlFor="ts-publish-title" className="block text-sm font-medium text-ink mb-2">Title</label>
                <input
                  id="ts-publish-title"
                  type="text"
                  value={selectedTitle || manualTitle}
                  onChange={(e) => selectedTitle ? setSelectedTitle(e.target.value) : setManualTitle(e.target.value)}
                  className="input-field font-display text-lg"
                  maxLength={100}
                  aria-describedby="ts-publish-title-count"
                />
                <p id="ts-publish-title-count" className="readout mt-2 text-right">{(selectedTitle || manualTitle).length} / 100</p>
              </div>

              {/* Description (still editable) */}
              <div>
                <div className="flex items-center justify-between gap-3 mb-2">
                  <label htmlFor="ts-publish-desc" className="text-sm font-medium text-ink">Description</label>
                  <span className="readout">{description.length} / 5000</span>
                </div>
                <textarea
                  id="ts-publish-desc"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  className="input-field resize-y min-h-[320px] lg:min-h-[420px] leading-relaxed custom-scrollbar"
                  maxLength={5000}
                />
              </div>
            </section>

            {/* Publish */}
            <aside aria-labelledby="ts-publish-heading" className="card-print p-5 sm:p-6 space-y-4 lg:sticky lg:top-2">
              <div>
                <h3 id="ts-publish-heading" className="font-display text-lg text-ink flex items-center gap-2">
                  <Youtube size={18} className="text-muted" aria-hidden="true" />
                  Publish
                </h3>
                <p className="text-sm text-muted mt-1">The video goes to your YouTube channel with this title, thumbnail and description.</p>
              </div>

              {/* Publish Button */}
              {(!managed && (!uploadPostKey || !uploadUserId)) ? (
                <div className="rounded-input border border-warn/40 bg-warn/10 p-4 space-y-3">
                  <p className="flex items-center gap-2 text-sm font-semibold text-ink">
                    <AlertCircle size={16} className="text-warn shrink-0" aria-hidden="true" />
                    Upload-Post not configured
                  </p>
                  <p className="text-sm text-ink2">
                    To publish straight to YouTube, add your Upload-Post API key and connect a profile in Settings.
                  </p>
                  {onOpenSettings && (
                    <button
                      type="button"
                      onClick={onOpenSettings}
                      className="btn-quiet"
                    >
                      <Settings size={14} aria-hidden="true" /> Go to Settings
                    </button>
                  )}
                </div>
              ) : (
                <button
                  type="button"
                  onClick={handlePublish}
                  disabled={isPublishing}
                  className="w-full btn-accent"
                >
                  {isPublishing ? (
                    <>
                      <Loader2 size={16} className="animate-spin" aria-hidden="true" />
                      Publishing to YouTube…
                    </>
                  ) : (
                    <>
                      <Youtube size={16} aria-hidden="true" />
                      Publish to YouTube
                    </>
                  )}
                </button>
              )}

              {/* Polling status */}
              {isPublishing && (
                <p className="readout flex items-center gap-2">
                  <Loader2 size={12} className="animate-spin shrink-0" aria-hidden="true" />
                  Uploading · checking status every 2 s
                </p>
              )}

              {/* Publish Result */}
              {publishResult && (
                publishResult.success ? (
                  <div className="rounded-input border border-ok/40 bg-ok/10 p-4 space-y-2">
                    <span className="badge-ok"><Check size={12} aria-hidden="true" /> Published</span>
                    <p className="text-sm font-semibold text-ink">Published successfully</p>
                    <p className="text-sm text-ink2">Your video is being uploaded to YouTube in the background.</p>
                    {onCreateClips && sessionId && (
                      <button
                        type="button"
                        onClick={() => onCreateClips(sessionId)}
                        className="btn-primary w-full mt-1"
                        title="Send this video and its transcript to the clip generator"
                      >
                        <Video size={16} aria-hidden="true" />
                        Create clips from this video
                      </button>
                    )}
                  </div>
                ) : (
                  <div role="alert" className="rounded-input border border-danger/40 bg-danger/10 p-4 space-y-2">
                    <span className="badge-danger"><AlertCircle size={12} aria-hidden="true" /> Failed</span>
                    <p className="text-sm font-semibold text-ink">Publish failed</p>
                    <p className="text-sm text-ink2 break-words">{publishResult.error}</p>
                  </div>
                )
              )}
            </aside>
          </div>
        )}
      </div>
    </div>
  );
}
