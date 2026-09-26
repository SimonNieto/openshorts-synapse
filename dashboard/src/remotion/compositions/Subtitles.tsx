import React from "react";
import {
  AbsoluteFill,
  Sequence,
  useCurrentFrame,
  useVideoConfig,
  spring,
  interpolate,
} from "remotion";
import type { SubtitleConfig } from "../lib/types";
import { groupCaptionsIntoBlocks, getActiveWordIndex } from "../lib/captions";
import { getFontStack } from "../lib/fonts";
import { ASS_OUTLINE_PX } from "../lib/assScale";

interface SubtitlesProps {
  config: SubtitleConfig;
}

// Legacy string presets, kept for any config saved before the slider existed.
const POSITION_MAP: Record<string, React.CSSProperties> = {
  top: { top: "12%", bottom: "auto" },
  middle: { top: "45%", bottom: "auto" },
  bottom: { bottom: "10%", top: "auto" },
};

// position is 0-100, % of frame height up from the bottom (matches
// subtitles.py's position_percent) — direct CSS `bottom` percentage, no
// conversion needed since both count from the same edge.
function positionStyleFor(position: number | string): React.CSSProperties {
  if (typeof position === "number") {
    return { bottom: `${position}%`, top: "auto" };
  }
  return POSITION_MAP[position] ?? POSITION_MAP.bottom;
}

export const Subtitles: React.FC<SubtitlesProps> = ({ config }) => {
  const { fps } = useVideoConfig();
  const blocks = groupCaptionsIntoBlocks(
    config.captions,
    config.maxChars ?? 20,
    config.maxDurationMs ?? 2000,
    config.maxWords
  );

  return (
    <AbsoluteFill>
      {blocks.map((block, i) => {
        const startFrame = Math.round((block.startMs / 1000) * fps);
        const durationFrames = Math.max(
          1,
          Math.round(((block.endMs - block.startMs) / 1000) * fps)
        );

        return (
          <Sequence
            key={i}
            from={startFrame}
            durationInFrames={durationFrames}
            layout="none"
          >
            <SubtitleBlock
              block={block}
              config={config}
              blockStartMs={block.startMs}
            />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};

interface SubtitleBlockProps {
  block: ReturnType<typeof groupCaptionsIntoBlocks>[number];
  config: SubtitleConfig;
  blockStartMs: number;
}

const SubtitleBlock: React.FC<SubtitleBlockProps> = ({
  block,
  config,
  blockStartMs,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { style, position } = config;

  // Current time relative to composition start (sequence-relative frame)
  const currentTimeMs = blockStartMs + (frame / fps) * 1000;
  const activeIndex = getActiveWordIndex(block.words, currentTimeMs);

  const positionStyle = positionStyleFor(position);
  const fontStack = getFontStack(style.fontFamily);

  // Background box style
  const hasBg = style.bgOpacity > 0;
  const bgStyle: React.CSSProperties = hasBg
    ? {
        backgroundColor: `${style.bgColor}${Math.round(style.bgOpacity * 255)
          .toString(16)
          .padStart(2, "0")}`,
        borderRadius: 8,
        padding: "8px 16px",
      }
    : {};

  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        display: "flex",
        justifyContent: "center",
        ...positionStyle,
      }}
    >
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "center",
          // Not the flex default (stretch): a highlight-box word sizes its
          // own filled rectangle from its padding, and stretching would make
          // it taller than the rectangle the burn draws.
          alignItems: "center",
          // Proportional to the type, like the burn: libass separates words by
          // the font's own space advance (~0.25em). A fixed 8px gap was
          // invisible at the real caption size, so words sat tighter here than
          // in the delivered clip and wrapped at different points.
          gap: `${style.fontSize * 0.18}px ${style.fontSize * 0.25}px`,
          maxWidth: "85%",
          ...bgStyle,
        }}
      >
        {block.words.map((word, i) => (
          <WordSpan
            key={i}
            word={word.text}
            isActive={i === activeIndex}
            style={style}
            fontStack={fontStack}
            animation={style.animation}
            frame={frame}
            fps={fps}
            wordStartMs={word.startMs}
            blockStartMs={blockStartMs}
          />
        ))}
      </div>
    </div>
  );
};

interface WordSpanProps {
  word: string;
  isActive: boolean;
  style: SubtitleConfig["style"];
  fontStack: string;
  animation: SubtitleConfig["style"]["animation"];
  frame: number;
  fps: number;
  wordStartMs: number;
  blockStartMs: number;
}

const WordSpan: React.FC<WordSpanProps> = ({
  word,
  isActive,
  style,
  fontStack,
  animation,
  frame,
  fps,
  wordStartMs,
  blockStartMs,
}) => {
  const wordStartFrame = Math.round(
    ((wordStartMs - blockStartMs) / 1000) * fps
  );

  let transform = "";
  let color = style.fontColor;
  let extraStyle: React.CSSProperties = {};
  // Set by effects whose burn counterpart clears the outline (\bord0\shad0).
  let suppressStroke = false;

  // Dim inactive words toward the backend's opaque scaled color (matches the
  // burned ASS look; not CSS opacity). Formula mirrors subtitles._dim_hex_color
  // exactly (factor = 0.5 + 0.5*opacity) — a different curve here used to make
  // the preview dim more aggressively than the actual burned video at the
  // same slider value.
  if (!isActive && style.baseOpacity != null && style.baseOpacity < 1) {
    const m = /^#?([0-9a-fA-F]{6})$/.exec(style.fontColor || "#FFFFFF");
    if (m) {
      const scale = 0.5 + 0.5 * style.baseOpacity;
      const [r, g, b] = [0, 2, 4].map((i) =>
        Math.round(parseInt(m[1].slice(i, i + 2), 16) * scale)
      );
      color = `rgb(${r}, ${g}, ${b})`;
    }
  }

  if (isActive) {
    color = style.highlightColor;

    switch (animation) {
      case "pop": {
        const scale = spring({
          frame: frame - wordStartFrame,
          fps,
          config: { mass: 0.5, stiffness: 300, damping: 12 },
          durationInFrames: 10,
        });
        const scaleValue = interpolate(scale, [0, 1], [1, 1.25]);
        transform = `scale(${scaleValue})`;
        break;
      }
      // "karaoke" = plain color swap on the active word (matches the real
      // burn's effect="none") — no box. A filled box used to render here,
      // which never matched what generate_ass actually produces for
      // effect="none", so the preview and the final video visibly disagreed.
      case "box": {
        // Mirrors generate_ass's effect="box": fill forced to white, a
        // thick colored OUTLINE (not a filled background) at borderWidth+3.
        // The +3 and the floor of 4 are ASS units in the burn, so convert
        // back out of pixels before applying them, then scale the result.
        color = "#FFFFFF";
        const bordUnits = (style.borderWidth || 0) / ASS_OUTLINE_PX;
        const boxBord = Math.max(4, bordUnits + 3) * ASS_OUTLINE_PX;
        extraStyle = {
          textShadow: [
            `${boxBord}px 0 0 ${style.highlightColor}`,
            `-${boxBord}px 0 0 ${style.highlightColor}`,
            `0 ${boxBord}px 0 ${style.highlightColor}`,
            `0 -${boxBord}px 0 ${style.highlightColor}`,
          ].join(", "),
        };
        break;
      }
      case "word-highlight": {
        extraStyle = {
          textShadow: `0 0 12px ${style.highlightColor}, 0 0 24px ${style.highlightColor}40`,
        };
        break;
      }
      case "highlight-box": {
        // Mirrors generate_ass's effect="highlight-box": a solid filled
        // rectangle behind the active word (not just an outline, unlike
        // "box"), with text in borderColor for contrast against the fill.
        // Same geometry as the drawn ASS rectangle: 0.22em of padding either
        // side, 0.30em above and below, square corners.
        color = style.borderColor || "#000000";
        // The burn draws this word with \bord0\shad0 — it already reads
        // against the filled box. Keeping the normal outline here painted a
        // borderColor-on-borderColor blob wider than the box itself.
        suppressStroke = true;
        extraStyle = {
          backgroundColor: style.highlightColor,
          borderRadius: 0,
          lineHeight: 1,
          padding: `${style.fontSize * 0.3}px ${style.fontSize * 0.22}px`,
        };
        break;
      }
      default:
        break;
    }
  }

  // Text stroke via textShadow (CSS paint-order not reliable in Remotion)
  const strokeShadow =
    style.borderWidth > 0 && !suppressStroke
      ? [
          `${style.borderWidth}px 0 0 ${style.borderColor}`,
          `-${style.borderWidth}px 0 0 ${style.borderColor}`,
          `0 ${style.borderWidth}px 0 ${style.borderColor}`,
          `0 -${style.borderWidth}px 0 ${style.borderColor}`,
        ].join(", ")
      : "none";

  return (
    <span
      style={{
        fontFamily: fontStack,
        fontSize: style.fontSize,
        letterSpacing: style.letterSpacing ? `${style.letterSpacing}px` : undefined,
        fontWeight: style.fontWeight ?? 700,
        color,
        textShadow: [strokeShadow, extraStyle.textShadow].filter(Boolean).join(", "),
        transform,
        display: "inline-block",
        transition: "none",
        textTransform: style.uppercase ? "uppercase" : "none",
        ...extraStyle,
      }}
    >
      {word}
    </span>
  );
};
