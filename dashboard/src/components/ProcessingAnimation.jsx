import React, { useEffect, useState, useRef } from 'react';
import { Activity } from 'lucide-react';
import { getApiUrl } from '../config';
import { apiFetch } from '../lib/api';

const ProcessingAnimation = ({ media, isComplete, syncedTime, isSyncedPlaying, syncTrigger, progress }) => {
  const [videoSrc, setVideoSrc] = useState(null);
  const [isYouTube, setIsYouTube] = useState(false);
  const videoRef = useRef(null);
  const iframeRef = useRef(null);

  useEffect(() => {
    if (!media) return;

    if (media.type === 'file') {
      const url = URL.createObjectURL(media.payload);
      setIsYouTube(false);
      setVideoSrc(url);
      return () => URL.revokeObjectURL(url);
    } else if (media.type === 'server') {
      // Uploaded source served from the backend (survives a page reload).
      // The payload is the plain /api/source/<job> path, because that is what
      // gets persisted; the signed URL is minted here, at render, so a stored
      // session never carries a token that has since expired. A <video> tag
      // cannot send the bearer header itself, hence the round trip.
      setIsYouTube(false);
      let cancelled = false;
      const jobId = media.payload.split('/').pop();
      (async () => {
        try {
          const res = await apiFetch(`/api/source-url/${jobId}`);
          const { url } = await res.json();
          if (!cancelled && url) setVideoSrc(getApiUrl(url));
        } catch (e) {
          // Self-host, or a backend without the endpoint: the open path still
          // works there, and losing the preview is worse than an unsigned URL.
          if (!cancelled) setVideoSrc(getApiUrl(media.payload));
        }
      })();
      return () => { cancelled = true; };
    } else if (media.type === 'url') {
      setIsYouTube(true);
      const videoId = getYouTubeId(media.payload);
      setVideoSrc(videoId);
    }
  }, [media]);

  // Handle Sync Playback for Local Video
  useEffect(() => {
    if (!isYouTube && videoRef.current) {
      if (isSyncedPlaying) {
        // Sync Mode: Seek to time and Play. A non-finite time (a clip with no
        // start yet) would throw and take the whole tree down — skip the seek.
        if (Number.isFinite(syncedTime)) videoRef.current.currentTime = syncedTime;
        videoRef.current.play().catch(e => console.log("Auto-play prevented", e));
        videoRef.current.loop = false;
        videoRef.current.muted = true; // Keep muted to avoid double audio with clip
      } else {
        // Stop Sync: Pause. Once analysis is complete, resume the ambient loop.
        videoRef.current.pause();

        if (isComplete) {
             videoRef.current.loop = true;
             videoRef.current.play().catch(e => console.log("Ambient play prevented", e));
        }
      }
    }
  }, [syncedTime, isSyncedPlaying, isYouTube, isComplete, syncTrigger]);

  // Handle Sync Playback for YouTube (Basic Iframe Control via PostMessage)
  useEffect(() => {
    if (isYouTube && iframeRef.current && videoSrc) {
        const iframeWindow = iframeRef.current.contentWindow;
        if (isSyncedPlaying) {
             // Seek and Play
             iframeWindow.postMessage(JSON.stringify({ event: 'command', func: 'seekTo', args: [syncedTime, true] }), '*');
             iframeWindow.postMessage(JSON.stringify({ event: 'command', func: 'playVideo', args: [] }), '*');
        } else {
             // Pause
             iframeWindow.postMessage(JSON.stringify({ event: 'command', func: 'pauseVideo', args: [] }), '*');
        }
    }
  }, [syncedTime, isSyncedPlaying, isYouTube, videoSrc, syncTrigger]);


  const getYouTubeId = (url) => {
    const regExp = /^.*(youtu.be\/|v\/|u\/\w\/|embed\/|watch\?v=|&v=)([^#&?]*).*/;
    const match = url.match(regExp);
    return (match && match[2].length === 11) ? match[2] : null;
  };

  // Three honest states, nothing invented on top of the footage: the job is
  // reading it, it is done with it, or it plays in step with a clip.
  const working = !isComplete && !isSyncedPlaying;
  const percent = Math.max(0, Math.min(100, progress?.percent ?? 0));

  const getVideoOpacityClass = () => {
    if (isSyncedPlaying) return 'opacity-100';     // Playing: full visibility
    if (isComplete) return 'opacity-50 grayscale'; // Idle result: stepped back
    return 'opacity-60 grayscale';                 // Processing: quiet, monochrome
  };

  const caption = isSyncedPlaying
    ? 'Playing in step with the clip'
    : isComplete
      ? 'Source video'
      : 'Reading the source';

  return (
    <figure className="min-w-0 animate-fade">
      {/* The plate: real media on true black, framed by a hairline. */}
      <div
        className={`relative w-full aspect-video rounded-card overflow-hidden bg-black border transition-colors duration-500
          ${isSyncedPlaying ? 'border-ink' : 'border-rule2'}`}
      >
        <div className={`absolute inset-0 transition-[opacity,filter] duration-700 ease-out ${getVideoOpacityClass()}`}>
          {isYouTube && videoSrc ? (
            <iframe
              ref={iframeRef}
              className={`w-full h-full ${isSyncedPlaying ? '' : 'pointer-events-none scale-110'}`}
              // Add enablejsapi=1 for postMessage control
              src={`https://www.youtube.com/embed/${videoSrc}?autoplay=1&mute=1&controls=0&loop=1&playlist=${videoSrc}&modestbranding=1&showinfo=0&rel=0&enablejsapi=1`}
              title="Source video preview"
              frameBorder="0"
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            />
          ) : videoSrc ? (
            <video
              ref={videoRef}
              src={videoSrc}
              className="w-full h-full object-cover"
              aria-label="Source video preview"
              autoPlay
              muted
              loop
              playsInline
            />
          ) : (
            <div className="w-full h-full flex flex-col items-center justify-center gap-3">
              <span aria-hidden="true" className={`h-2 w-2 rounded-full bg-muted ${isComplete ? '' : 'neural-node'}`} />
              <span className="readout">Loading preview</span>
            </div>
          )}
        </div>

        {/* The job's real percent (app.py _job_progress) as a hairline along
            the plate's lower edge. The number itself lives in the progress
            header; this only mirrors it, so it is hidden from screen readers. */}
        {working && (
          <div aria-hidden="true" className="absolute inset-x-0 bottom-0 h-0.5 bg-[color:var(--color-rule)]">
            <div
              className="h-full bg-ink transition-[width] duration-700 ease-out"
              style={{ width: `${Math.max(2, percent)}%` }}
            />
          </div>
        )}
      </div>

      <figcaption className="mt-2.5 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 min-w-0">
        <span className="flex items-center gap-2 min-w-0">
          {working && (
            /* A filament drawing itself while the job reads the footage. */
            <svg aria-hidden="true" width="34" height="10" viewBox="0 0 34 10" className="shrink-0 text-ink2 overflow-visible">
              <path
                d="M1 6 C7 1, 12 9, 18 5 S26 2, 29 5"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.2"
                strokeLinecap="round"
                style={{ strokeDasharray: 40, '--ink-len': 40, animation: 'ink-draw 2.8s var(--ease-out) infinite alternate' }}
              />
              <circle cx="31" cy="5" r="2" fill="currentColor" className="neural-node" />
            </svg>
          )}
          {isSyncedPlaying && <Activity size={13} aria-hidden="true" className="shrink-0 text-ink" />}
          <span className={`readout truncate ${isSyncedPlaying ? 'text-ink' : ''}`}>{caption}</span>
        </span>
        {isComplete && !isSyncedPlaying && (
          <span className="readout">Play a clip to follow it here</span>
        )}
      </figcaption>
    </figure>
  );
};

export default ProcessingAnimation;
