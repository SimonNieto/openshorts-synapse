import React, { useState, useEffect } from 'react';
import { Film, Download, Copy, Check, Loader2, Play, User } from 'lucide-react';
import { getApiUrl } from '../config';
import SegmentedControl from './ui/SegmentedControl';
import Modal from './ui/Modal';

export default function UGCGallery() {
  const [tab, setTab] = useState('videos');
  const [videos, setVideos] = useState([]);
  const [avatars, setAvatars] = useState([]);
  const [loadingVideos, setLoadingVideos] = useState(true);
  const [loadingAvatars, setLoadingAvatars] = useState(false);
  const [avatarsLoaded, setAvatarsLoaded] = useState(false);
  const [copied, setCopied] = useState('');
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    setLoadingVideos(true);
    fetch(getApiUrl('/api/saasshorts/gallery?limit=100'))
      .then((r) => (r.ok ? r.json() : { videos: [] }))
      .then((d) => setVideos(d.videos || []))
      .catch(() => {})
      .finally(() => setLoadingVideos(false));
  }, []);

  useEffect(() => {
    if (tab !== 'avatars' || avatarsLoaded) return;
    setLoadingAvatars(true);
    fetch(getApiUrl('/api/saasshorts/actor-gallery'))
      .then((r) => (r.ok ? r.json() : { images: [] }))
      .then((d) => setAvatars(d.images || []))
      .catch(() => {})
      .finally(() => {
        setLoadingAvatars(false);
        setAvatarsLoaded(true);
      });
  }, [tab, avatarsLoaded]);

  const handleCopy = (text, id) => {
    navigator.clipboard.writeText(text);
    setCopied(id);
    setTimeout(() => setCopied(''), 2000);
  };

  const loading = (tab === 'videos' && loadingVideos) || (tab === 'avatars' && loadingAvatars);

  return (
    <section aria-labelledby="ugc-title" className="space-y-8">
      <header className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
        <div className="min-w-0">
          <p className="eyebrow mb-2">Library</p>
          <h2 id="ugc-title" className="page-title">AI actor videos</h2>
          <p className="page-lede mt-3">
            Videos shared to the public gallery from AI Shorts, and the AI actors generated so far.
          </p>
        </div>
        <p className="readout shrink-0">
          {loadingVideos ? '…' : videos.length} videos
          {avatarsLoaded ? ` · ${avatars.length} actors` : ''}
        </p>
      </header>

      <div className="max-w-xs w-full" role="group" aria-label="Show">
        <SegmentedControl
          size="sm"
          value={tab}
          onChange={setTab}
          options={[
            { value: 'videos', label: `Videos (${loadingVideos ? '…' : videos.length})`, icon: <Film size={14} /> },
            { value: 'avatars', label: `Actors (${avatarsLoaded ? avatars.length : '…'})`, icon: <User size={14} /> },
          ]}
        />
      </div>

      {loading ? (
        <div role="status" aria-live="polite" className="tray flex items-center justify-center gap-2 h-64 text-sm text-muted">
          <Loader2 size={18} className="animate-spin" aria-hidden="true" />
          Loading the gallery…
        </div>
      ) : tab === 'videos' ? (
        videos.length === 0 ? (
          <EmptyPlate
            image="/landing/voice.jpg"
            title="No shared videos yet"
            text={'Generate a video in AI Shorts and tick “Share this video in the public gallery” before you generate: it will show up here.'}
          />
        ) : (
          <ul className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-x-4 gap-y-8">
            {videos.map((video) => (
              <li key={video.video_id} className="min-w-0">
                <VideoCard
                  video={video}
                  copied={copied}
                  onCopy={handleCopy}
                  onOpen={() => setSelected(video)}
                />
              </li>
            ))}
          </ul>
        )
      ) : avatars.length === 0 ? (
        <EmptyPlate
          image="/landing/frustration.jpg"
          title="No actors yet"
          text="Generate actors in AI Shorts, at the cast step: every one you make is kept here."
        />
      ) : (
        <ul className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-x-4 gap-y-6">
          {avatars.map((avatar, i) => (
            <li key={avatar.key || i} className="min-w-0">
              <AvatarCard avatar={avatar} copied={copied} onCopy={handleCopy} />
            </li>
          ))}
        </ul>
      )}

      {selected && (
        <Modal
          isOpen
          onClose={() => setSelected(null)}
          size="sm"
          eyebrow={selected.video_mode === 'lowcost' ? 'Low cost' : 'Premium'}
          title={selected.title || 'Untitled'}
        >
          <video
            src={selected.video_url}
            poster={selected.actor_url}
            controls
            autoPlay
            playsInline
            className="w-full rounded-input bg-black border border-rule2 aspect-[9/16] object-contain max-h-[60vh]"
          />
          <p className="readout mt-3">
            {selected.duration?.toFixed(0)}s
            {selected.cost_estimate?.total != null ? ` · $${selected.cost_estimate.total.toFixed(2)}` : ''}
          </p>
          {selected.caption && (
            <p className="text-sm text-ink2 mt-2 leading-relaxed break-words">{selected.caption}</p>
          )}
          <a
            href={selected.video_url}
            download
            className="btn-primary w-full mt-5"
          >
            <Download size={16} aria-hidden="true" /> Download
          </a>
        </Modal>
      )}
    </section>
  );
}

// An empty shelf: one drawn plate on black, then what to do next.
function EmptyPlate({ image, title, text }) {
  return (
    <div className="tray p-4 sm:p-8 grid gap-6 sm:grid-cols-[minmax(0,18rem)_minmax(0,1fr)] items-center">
      <figure>
        <div className="aspect-[16/10] bg-black border border-rule2 rounded-card overflow-hidden">
          <img src={image} alt="" loading="lazy" decoding="async" className="w-full h-full object-cover" />
        </div>
        <figcaption className="readout mt-2">B-roll drawn by Synapse AI</figcaption>
      </figure>
      <div className="min-w-0">
        <h3 className="font-display text-xl sm:text-2xl text-ink">{title}</h3>
        <p className="text-sm text-muted mt-2 leading-relaxed max-w-md">{text}</p>
      </div>
    </div>
  );
}

function AvatarCard({ avatar, copied, onCopy }) {
  return (
    <article className="min-w-0">
      <div className="aspect-[3/4] bg-black border border-rule2 rounded-card overflow-hidden">
        <img
          src={avatar.url}
          alt="AI actor portrait"
          loading="lazy"
          decoding="async"
          className="w-full h-full object-cover"
        />
      </div>
      <div className="pt-2.5 space-y-2">
        {avatar.description ? (
          <p className="text-xs text-muted line-clamp-3 leading-relaxed">{avatar.description}</p>
        ) : (
          <p className="text-xs text-muted">No description</p>
        )}
        <div className="flex items-center gap-1.5">
          {avatar.description && (
            <button
              type="button"
              onClick={() => onCopy(avatar.description, `avatar-${avatar.key}`)}
              className="btn-quiet text-xs px-2.5 py-1.5 shrink-0"
              aria-label={copied === `avatar-${avatar.key}` ? 'Prompt copied' : 'Copy prompt'}
              title="Copy prompt"
            >
              {copied === `avatar-${avatar.key}` ? <Check size={14} className="text-ok" aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
            </button>
          )}
          <a
            href={avatar.url}
            download
            className="btn-quiet text-xs px-2.5 py-1.5 flex-1 min-w-0"
          >
            <Download size={14} aria-hidden="true" /> Download
          </a>
        </div>
      </div>
    </article>
  );
}

function VideoCard({ video, copied, onCopy, onOpen }) {
  const mode = video.video_mode;
  const caption = video.caption || '';
  const hashtags = (video.hashtags || []).join(' ');

  return (
    <article className="min-w-0">
      <button
        type="button"
        onClick={onOpen}
        aria-label={`Play ${video.title || 'Untitled'}`}
        className="group relative block aspect-[9/16] w-full bg-black border border-rule2 rounded-card overflow-hidden cursor-pointer transition-colors duration-200 hover:border-ink/50"
      >
        {video.actor_url ? (
          <img
            src={video.actor_url}
            alt=""
            loading="lazy"
            decoding="async"
            className="w-full h-full object-cover"
          />
        ) : (
          <span className="block w-full h-full bg-paper3" />
        )}
        <span
          aria-hidden="true"
          className="absolute left-2 bottom-2 w-9 h-9 rounded-full bg-paper/80 border border-rule2 flex items-center justify-center text-ink transition-colors group-hover:bg-paper"
        >
          <Play size={15} className="ml-0.5" />
        </span>
        <span className="absolute top-2 left-2 readout text-ink2 bg-paper/90 border border-rule2 rounded px-1.5 py-0.5">
          {mode === 'lowcost' ? 'Low cost' : 'Premium'}
        </span>
      </button>

      <div className="pt-2.5 space-y-1.5">
        <h3 className="text-sm font-semibold text-ink leading-snug line-clamp-2 break-words">{video.title || 'Untitled'}</h3>
        <p className="readout">
          {video.duration?.toFixed(0)}s · ${video.cost_estimate?.total?.toFixed(2) || '?'}
        </p>
        {caption && (
          <p className="text-xs text-muted line-clamp-2 leading-relaxed">{caption}</p>
        )}
        <div className="flex items-center gap-1.5 pt-1">
          {caption && (
            <button
              type="button"
              onClick={() => onCopy(`${caption}\n${hashtags}`, `caption-${video.video_id}`)}
              className="btn-quiet text-xs px-2.5 py-1.5 shrink-0"
              aria-label={copied === `caption-${video.video_id}` ? 'Caption copied' : 'Copy caption and hashtags'}
              title="Copy caption"
            >
              {copied === `caption-${video.video_id}` ? <Check size={14} className="text-ok" aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
            </button>
          )}
          <a
            href={video.video_url}
            download
            className="btn-quiet text-xs px-2.5 py-1.5 flex-1 min-w-0"
          >
            <Download size={14} aria-hidden="true" /> Download
          </a>
        </div>
      </div>
    </article>
  );
}
