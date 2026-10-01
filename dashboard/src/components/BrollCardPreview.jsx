import React, { useEffect, useRef, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { apiJson } from '../lib/api';
import { getApiUrl } from '../config';

// Mirror of broll._rise_box for the settled card: the size asked for is honoured, only the frame's edges cut it.
// The caption band, the band under it and the limits come from the backend (broll.rise_geometry), so the
// preview cannot drift from what the video gets; only this arithmetic runs here, to follow the slider live.
function cardBox(g, position, sizePct, aspect, yPct) {
    const size = Math.max(18, Math.min(64, Math.floor(Number(sizePct)) || 28));
    const wanted = Math.floor((g.W * size) / 100);
    const chMax = yPct != null ? g.hard_bottom - g.hard_top
        : position === 'above' ? g.band_bottom - g.hard_top
            : position === 'top' ? g.band_bottom - g.band_top
                : g.hard_bottom - g.band_top;
    let cw = wanted;
    if (cw * aspect > chMax) cw = Math.floor(Math.max(chMax, g.H * 0.08) / aspect);
    const ch = Math.floor(cw * aspect);
    const yEnd = yPct != null
        ? Math.min(Math.max((g.H * yPct) / 100, g.hard_top + ch / 2), g.hard_bottom - ch / 2)
        : position === 'above' ? g.band_bottom - ch / 2
            : position === 'top' ? (g.band_top + g.band_bottom) / 2
                : Math.max((g.band_top + g.band_bottom) / 2, g.band_top + ch / 2);
    return { x: (g.W - cw) / 2, y: yEnd - ch / 2, w: cw, h: ch, wanted, limited: cw < wanted };
}

/**
 * Live preview of the small B-roll card on one frame of one of your clips: the captions are drawn where this
 * edit style puts them, the yellow line is the app-zone limit, and the card follows the size slider as you
 * drag it. The size is honoured; a card past the free band simply extends over the app's buttons zone.
 * ``aspect`` fixes the picture's shape (the wide 16:10 cards of the mixed layout) and ``allowY`` turns the
 * free-height drag off (those cards are placed by their position alone).
 */
// The edge and shadow of the card, as broll.BORDERS draws them.
const EDGE_CSS = {
    strong: { border: '1.5px solid rgba(255,255,255,0.92)', boxShadow: '0 3px 10px rgba(0,0,0,0.6)' },
    soft: { border: '1px solid rgba(255,255,255,0.42)', boxShadow: '0 3px 14px rgba(0,0,0,0.33)' },
    none: { border: 'none', boxShadow: 'none' },
    premium: { border: '1px solid rgba(255,255,255,0.12)', boxShadow: '0 6px 28px rgba(0,0,0,0.24)' },
};
const POSITIONS = ['above', 'top'];

export default function BrollCardPreview({ style, watermark, position, size, y, border, onSize, onY, aspect: fixedAspect, allowY = true }) {
    const [clips, setClips] = useState(null);
    const [clip, setClip] = useState('');
    const [t, setT] = useState(3);
    const [g, setG] = useState(null);
    const [picAspect, setPicAspect] = useState(1);
    const aspect = fixedAspect || picAspect;
    const [zones, setZones] = useState(true);
    const stage = useRef(null);
    const grab = useRef(null);      // while dragging: how far the pointer is from the card's centre (% of the height)

    useEffect(() => {
        let live = true;
        apiJson('/api/plus/broll/preview/clips')
            .then((d) => { if (live) { setClips(d.clips || []); if (d.clips?.length) setClip(d.clips[0].id); } })
            .catch(() => { if (live) setClips([]); });
        return () => { live = false; };
    }, []);

    const pos = POSITIONS.includes(position) ? position : 'below';
    useEffect(() => {
        let live = true;
        apiJson(`/api/plus/broll/geometry?edit_style=${encodeURIComponent(style || 'natural')}&watermark=${watermark ? 1 : 0}`
            + `&position=${pos}&size=28`)
            .then((d) => { if (live) setG(d); })
            .catch(() => { if (live) setG(null); });
        return () => { live = false; };
    }, [style, watermark, pos]);

    if (clips === null) return null;
    if (clips.length === 0) {
        return <p className="text-xs text-muted mt-1">Live preview: generate one clip first, its frame will show here.</p>;
    }
    const cur = clips.find((c) => c.id === clip) || clips[0];
    const yUsed = allowY ? y : null;
    const box = g ? cardBox(g, pos, size, aspect, yUsed) : null;
    const pct = (v, total) => `${(100 * v) / total}%`;
    const intoApp = box && (yUsed != null || !POSITIONS.includes(pos)) && box.y + box.h > g.platform_y;
    const pointerPct = (e) => {
        const r = stage.current.getBoundingClientRect();
        return ((e.clientY - r.top) / r.height) * 100;
    };
    const centrePct = () => ((box.y + box.h / 2) / g.H) * 100;
    const startDrag = (e) => {
        if (!allowY || !box || !stage.current) return;
        e.preventDefault();
        try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* not a real pointer: keep going */ }
        grab.current = pointerPct(e) - centrePct();
        if (y == null) onY(Math.round(centrePct() * 10) / 10);
    };
    const moveDrag = (e) => {
        if (!allowY || grab.current === null || !stage.current) return;
        onY(Math.max(3, Math.min(97, Math.round((pointerPct(e) - grab.current) * 10) / 10)));
    };
    const endDrag = () => { grab.current = null; };
    const frameSrc = getApiUrl(`/api/plus/broll/preview/frame?clip=${encodeURIComponent(cur.id)}&t=${t}`);

    return (
        <div className="mt-2 flex flex-wrap items-start gap-4">
            <div ref={stage} className="relative overflow-hidden rounded-input bg-paper3 shrink-0" style={{ width: 216, aspectRatio: '9 / 16' }}>
                <img src={frameSrc} alt="frame of your clip" className="absolute inset-0 w-full h-full object-cover" />
                {g && (
                    <>
                        <div className="absolute left-0 right-0 flex items-center justify-center text-[10px] font-bold text-white/90 tracking-wide"
                            style={{ top: pct(g.cap_top, g.H), height: pct(g.cap_bottom - g.cap_top, g.H), background: 'rgba(0,0,0,0.25)',
                                borderTop: '1px dashed rgba(255,255,255,0.5)', borderBottom: '1px dashed rgba(255,255,255,0.5)' }}>
                            CAPTIONS
                        </div>
                        {zones && (
                            <>
                                <div className="absolute left-0 right-0 bottom-0 pointer-events-none"
                                    style={{ top: '78%', background: 'rgba(255,60,60,0.28)' }} />
                                <div className="absolute left-0 right-0 pointer-events-none"
                                    style={{ top: pct(g.platform_y, g.H), borderTop: '2px solid #ffd84d' }} />
                            </>
                        )}
                        {cur.picture && box && (
                            <img src={getApiUrl(cur.picture)} alt="sample card"
                                onLoad={(e) => setPicAspect(Math.min(1.25, Math.max(0.75, e.target.naturalHeight / e.target.naturalWidth)))}
                                onPointerDown={startDrag} onPointerMove={moveDrag} onPointerUp={endDrag} onPointerCancel={endDrag}
                                draggable={false}
                                className={`absolute object-cover ${allowY ? 'cursor-grab active:cursor-grabbing' : ''}`}
                                style={{ left: pct(box.x, g.W), top: pct(box.y, g.H), width: pct(box.w, g.W), height: pct(box.h, g.H),
                                    borderRadius: fixedAspect ? '3%' : '7%', ...(EDGE_CSS[border] || EDGE_CSS.soft), touchAction: 'none' }} />
                        )}
                    </>
                )}
            </div>
            <div className="grow min-w-[190px] space-y-2 text-xs text-muted">
                <label className="flex flex-col gap-1">
                    frame from
                    <select value={cur.id} onChange={(e) => setClip(e.target.value)} className="input-field text-xs py-1 px-2">
                        {clips.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
                    </select>
                </label>
                <button type="button" onClick={() => setT(Math.round((1 + Math.random() * 25) * 10) / 10)}
                    className="btn-quiet px-2.5 py-1 text-xs inline-flex items-center gap-1.5">
                    <RefreshCw size={13} /> another frame
                </button>
                <label className="flex flex-col gap-1">
                    <span>size: <span className="text-ink">{Math.round(Number(size) || 28)}%</span> of the width</span>
                    <input type="range" min="18" max={fixedAspect ? 64 : 60} step="1" value={Math.round(Number(size) || 28)}
                        onChange={(e) => onSize(Number(e.target.value))} className="w-full accent-[var(--color-accent)]" />
                </label>
                {allowY && (
                    <label className="flex flex-col gap-1">
                        <span>height: <span className="text-ink">{y != null ? `${Math.round(y)}%` : 'automatic'}</span>{y != null ? ' from the top' : ' (drag the card, or move this)'}</span>
                        <input type="range" min="3" max="97" step="0.5"
                            value={y != null ? y : Math.round(((box ? box.y + box.h / 2 : 0.72 * 1920) / (g ? g.H : 1920)) * 1000) / 10}
                            onChange={(e) => onY(Number(e.target.value))} className="w-full accent-[var(--color-accent)]" />
                    </label>
                )}
                {box && (
                    <p className={intoApp || box.limited ? 'text-brass' : ''}>
                        {box.limited
                            ? (pos === 'top' ? 'Narrowed to fit above the head.' : 'Cut by the edge of the screen.')
                            : intoApp
                                ? 'Past the yellow line: it covers the app’s own buttons area on a phone (your choice).'
                                : yUsed != null ? 'Where you put it.'
                                    : pos === 'top' ? 'In the free band above the head, once the hook is gone.'
                                        : pos === 'above' ? 'Just above the captions.' : 'Inside the free space under the captions.'}
                    </p>
                )}
                <label className="flex items-center gap-1.5 cursor-pointer select-none">
                    <input type="checkbox" checked={zones} onChange={(e) => setZones(e.target.checked)}
                        className="w-3.5 h-3.5 accent-[var(--color-accent)]" />
                    show the app zone (approximate)
                </label>
                <p className="text-[11px] leading-relaxed">Your clip’s frame, without hook or captions; captions are drawn where this edit style puts them. Red = roughly where TikTok / Reels / Shorts draw their text and buttons; yellow = the limit used by the editor.</p>
            </div>
        </div>
    );
}
