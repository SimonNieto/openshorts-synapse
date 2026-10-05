import { useState } from 'react';
import { Play } from 'lucide-react';
import { getApiUrl } from '../../config';

/**
 * A clip's 9:16 picture on black (design.md: media sit on black with a hairline). The server's still
 * (thumb_url, the rendered clip at ~1.5 s); if it can't be had, the video's own first frame. With
 * `onPlay` it is the button that plays the clip. `crop`: a square cut around the speaker's face and the set
 * (the week strip: enough to see at a glance that two posts look alike).
 */
export default function ClipThumb({ clip, onPlay, className = '', showPlay = true, crop = false }) {
  const [broken, setBroken] = useState(false);
  const picture = clip.thumb_url && !broken ? (
    <img
      src={getApiUrl(clip.thumb_url)}
      alt=""
      loading="lazy"
      decoding="async"
      onError={() => setBroken(true)}
      className={`absolute inset-0 w-full h-full object-cover ${crop ? 'object-center' : ''}`}
    />
  ) : clip.video_url ? (
    <video
      src={`${getApiUrl(clip.video_url)}#t=1.5`}
      preload="metadata"
      muted
      playsInline
      aria-hidden="true"
      tabIndex={-1}
      className={`absolute inset-0 w-full h-full object-cover pointer-events-none ${crop ? 'object-center' : ''}`}
    />
  ) : null;
  const frame = `relative block ${crop ? 'aspect-square' : 'aspect-[9/16]'} bg-black border border-rule2 rounded-input overflow-hidden shrink-0 ${className}`;
  if (!onPlay) return <span className={frame} aria-hidden="true">{picture}</span>;
  return (
    <button
      type="button"
      onClick={onPlay}
      className={`${frame} group hover:border-ink transition-colors`}
      aria-label={`Play “${clip.title || 'clip'}”`}
    >
      {picture}
      {showPlay && (
        <span className="absolute inset-0 flex items-center justify-center bg-paper/0 group-hover:bg-paper/30 transition-colors" aria-hidden="true">
          <span className="w-8 h-8 rounded-full bg-paper/80 border border-rule2 flex items-center justify-center opacity-80 group-hover:opacity-100">
            <Play size={14} className="text-ink translate-x-[1px]" />
          </span>
        </span>
      )}
    </button>
  );
}
