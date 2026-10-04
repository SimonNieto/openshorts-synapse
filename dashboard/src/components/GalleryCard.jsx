import React, { useRef, useState, useEffect } from 'react';
import { Download, Copy, Check, Play } from 'lucide-react';

export default function GalleryCard({ clip }) {
    const [copied, setCopied] = useState(null);
    const [isVisible, setIsVisible] = useState(false);
    const [_hasLoaded, setHasLoaded] = useState(false);
    const cardRef = useRef(null);
    const videoRef = useRef(null);

    // Lazy loading with IntersectionObserver
    useEffect(() => {
        const observer = new IntersectionObserver(
            (entries) => {
                entries.forEach((entry) => {
                    if (entry.isIntersecting) {
                        setIsVisible(true);
                        // Once loaded, we don't need to observe anymore
                        observer.unobserve(entry.target);
                    }
                });
            },
            {
                rootMargin: '200px', // Start loading 200px before entering viewport
                threshold: 0.1
            }
        );

        const node = cardRef.current;
        if (node) {
            observer.observe(node);
        }

        return () => {
            if (node) {
                observer.unobserve(node);
            }
        };
    }, []);

    const handleCopy = (text, field) => {
        navigator.clipboard.writeText(text);
        setCopied(field);
        setTimeout(() => setCopied(null), 2000);
    };

    const handleDownload = async (e) => {
        e.preventDefault();
        try {
            const response = await fetch(clip.url);
            if (!response.ok) throw new Error('Download failed');
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = url;
            a.download = `clip_${clip.job_id}_${clip.index + 1}.mp4`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        } catch (err) {
            console.error('Download error:', err);
            window.open(clip.url, '_blank');
        }
    };

    const caption = clip.tiktok_desc || clip.insta_desc;

    return (
        <article
            ref={cardRef}
            aria-label={clip.title}
            className="card card-hover w-full overflow-hidden flex flex-col animate-fade"
        >
            {/* The plate: the clip on black, lazy loaded. */}
            <div className="aspect-[9/16] bg-black border-b border-rule2 relative">
                {isVisible ? (
                    <video
                        ref={videoRef}
                        src={clip.url}
                        controls
                        className="w-full h-full object-cover"
                        playsInline
                        preload="metadata"
                        aria-label={clip.title}
                        onLoadedData={() => setHasLoaded(true)}
                    />
                ) : (
                    <div className="w-full h-full flex items-center justify-center" aria-hidden="true">
                        <span className="w-12 h-12 rounded-full border border-rule2 flex items-center justify-center">
                            <Play size={20} className="text-muted ml-0.5" />
                        </span>
                    </div>
                )}
            </div>

            {/* Content & Details */}
            <div className="flex-1 p-4 flex flex-col gap-4 min-w-0">
                <div>
                    <h3 className="font-display text-base text-ink leading-snug line-clamp-2 break-words" title={clip.title}>
                        {clip.title}
                    </h3>
                    <p className="readout mt-1.5 flex flex-wrap gap-x-2 gap-y-1">
                        <span>{new Date(clip.created_at).toLocaleDateString()}</span>
                        <span aria-hidden="true">·</span>
                        <span>{clip.duration.toFixed(1)}s</span>
                        <span aria-hidden="true">·</span>
                        <span className="truncate max-w-[150px]" title={clip.job_id}>ID {clip.job_id.substring(0, 8)}</span>
                    </p>
                </div>

                <div className="space-y-3 flex-1 overflow-y-auto custom-scrollbar max-h-[180px] pr-1">
                    {/* YouTube Title */}
                    <div className="tray p-3">
                        <div className="flex items-center justify-between gap-2">
                            <p className="readout">YouTube title</p>
                            <button
                                type="button"
                                onClick={() => handleCopy(clip.title, 'yt')}
                                aria-label={copied === 'yt' ? 'YouTube title copied' : 'Copy YouTube title'}
                                className="-m-1.5 p-1.5 rounded-input text-muted hover:text-ink transition-colors [@media(pointer:coarse)]:min-h-[44px] [@media(pointer:coarse)]:min-w-[44px] inline-flex items-center justify-center"
                            >
                                {copied === 'yt' ? <Check size={14} className="text-ok" aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
                            </button>
                        </div>
                        <p className="text-xs text-ink2 mt-1 select-all line-clamp-2 hover:line-clamp-none break-words">{clip.title}</p>
                    </div>

                    {/* TikTok / IG Caption */}
                    <div className="tray p-3">
                        <div className="flex items-center justify-between gap-2">
                            <p className="readout">TikTok · Instagram caption</p>
                            <button
                                type="button"
                                onClick={() => handleCopy(clip.tiktok_desc || clip.insta_desc, 'caption')}
                                aria-label={copied === 'caption' ? 'Caption copied' : 'Copy caption'}
                                className="-m-1.5 p-1.5 rounded-input text-muted hover:text-ink transition-colors [@media(pointer:coarse)]:min-h-[44px] [@media(pointer:coarse)]:min-w-[44px] inline-flex items-center justify-center"
                            >
                                {copied === 'caption' ? <Check size={14} className="text-ok" aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
                            </button>
                        </div>
                        <p className="text-xs text-ink2 mt-1 select-all line-clamp-3 hover:line-clamp-none break-words">{caption}</p>
                    </div>
                </div>
                <p className="sr-only" aria-live="polite">{copied ? 'Copied to the clipboard' : ''}</p>

                {/* Footer Action */}
                <button
                    type="button"
                    onClick={handleDownload}
                    className="btn-ghost w-full"
                >
                    <Download size={14} className="shrink-0" aria-hidden="true" /> Download clip
                </button>
            </div>
        </article>
    );
}
