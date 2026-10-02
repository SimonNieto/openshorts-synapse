import React from "react";
import {
  AbsoluteFill,
  Sequence,
  useCurrentFrame,
  useVideoConfig,
  spring,
  interpolate,
} from "remotion";
import type { HookConfig } from "../lib/types";
import {
  notoSerifFontFace,
  NOTO_SERIF_FONT_FAMILY,
  montserratFontFace,
  MONTSERRAT_FONT_FAMILY,
} from "../lib/fonts";

interface HookOverlayProps {
  config: HookConfig;
}

const SIZE_SCALE: Record<string, number> = {
  S: 0.8,
  M: 1.0,
  L: 1.3,
};

// Percentages must match hooks.py's overlay_y math (top 20% / bottom 70%),
// or the preview drifts from what the server path renders.
const POSITION_STYLE: Record<string, React.CSSProperties> = {
  top: { top: "20%", bottom: "auto" },
  center: { top: "50%", bottom: "auto", transform: "translateY(-50%)" },
  bottom: { top: "70%", bottom: "auto" },
};

// Must mirror hooks.py HOOK_STYLES (the server-side FFmpeg fallback).
interface HookLook {
  box: string | null;
  text: string;
  outlinePx: number;
  shadow: boolean;
}

const HOOK_LOOKS: Record<string, HookLook> = {
  classic: { box: "rgba(255, 255, 255, 0.94)", text: "#000000", outlinePx: 0, shadow: true },
  dark: { box: "rgba(18, 18, 20, 0.92)", text: "#FFFFFF", outlinePx: 0, shadow: true },
  yellow: { box: "rgba(255, 214, 0, 0.96)", text: "#000000", outlinePx: 0, shadow: true },
  red: { box: "rgba(220, 38, 38, 0.96)", text: "#FFFFFF", outlinePx: 0, shadow: true },
  outline: { box: null, text: "#FFFFFF", outlinePx: 8, shadow: false },
  outline_yellow: { box: null, text: "#FFD600", outlinePx: 8, shadow: false },
};

export const HookOverlay: React.FC<HookOverlayProps> = ({ config }) => {
  const { fps } = useVideoConfig();
  const displayFrames = Math.round(config.displayDurationSec * fps);

  if (config.style === "docline") {
    return (
      <AbsoluteFill>
        <style>{montserratFontFace}</style>
        <Sequence from={0} durationInFrames={displayFrames} layout="none">
          <DoclineBox config={config} displayFrames={displayFrames} />
        </Sequence>
      </AbsoluteFill>
    );
  }

  return (
    <AbsoluteFill>
      <style>{notoSerifFontFace}</style>
      <Sequence from={0} durationInFrames={displayFrames} layout="none">
        <HookBox config={config} displayFrames={displayFrames} />
      </Sequence>
    </AbsoluteFill>
  );
};

// The documentary line (hooks.py DOCLINE): a short rule that draws itself,
// then the title, left-aligned, its letter-spacing closing in, under a soft
// veil. The burn also draws the clip's topic above the rule, colours the
// brain's payoff word and keeps the topic and the rule once the title has
// gone; the preview knows neither word, so it shows the title's own life.
// Timings in seconds, as in DOCLINE: veil (0, .15), rule (.1, .35),
// title (.25, .4), exit .2.
const ramp = (t: number, start: number, length: number) =>
  Math.min(1, Math.max(0, (t - start) / length));
const easeOut = (f: number) => 1 - Math.pow(1 - f, 3);

const DoclineBox: React.FC<HookBoxProps> = ({ config, displayFrames }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const px = width / 1080;
  const t = frame / fps;
  const veil = ramp(t, 0, 0.15);
  const rule = easeOut(ramp(t, 0.1, 0.35));
  const title = ramp(t, 0.25, 0.4);
  const out = interpolate(frame, [displayFrames - 0.2 * fps, displayFrames], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const tracking = 0.25 + (0.01 - 0.25) * easeOut(title);
  const fontSize = Math.round(56 * px * (SIZE_SCALE[config.size] ?? 1.0));

  return (
    <AbsoluteFill>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: 0,
          height: "32%",
          opacity: veil * out,
          background:
            "linear-gradient(rgba(0,0,0,0.6) 0%, rgba(0,0,0,0.6) 17%, rgba(0,0,0,0) 100%)",
        }}
      />
      <div
        style={{
          position: "absolute",
          left: "6%",
          right: "10%",
          top: `${0.11 * height}px`,
        }}
      >
        <div
          style={{
            height: Math.max(2, Math.round(4 * px)),
            width: `${30 * rule}%`,
            background: "#FFFFFF",
            opacity: veil,
            marginBottom: Math.round(18 * px),
          }}
        />
        <div
          style={{
            fontFamily: `'${MONTSERRAT_FONT_FAMILY}', Montserrat, 'Arial Black', sans-serif`,
            fontWeight: 800,
            fontSize,
            lineHeight: 1.22,
            letterSpacing: `${tracking}em`,
            color: "#FFFFFF",
            opacity: title * title * out,
            textShadow: `0 ${Math.round(3 * px)}px ${Math.round(10 * px)}px rgba(0,0,0,0.9)`,
          }}
        >
          {config.text}
        </div>
      </div>
    </AbsoluteFill>
  );
};

interface HookBoxProps {
  config: HookConfig;
  displayFrames: number;
}

const HookBox: React.FC<HookBoxProps> = ({ config, displayFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const scale = SIZE_SCALE[config.size] ?? 1.0;

  // Entrance animation
  let animOpacity = 1;
  let animScale = 1;
  let animTranslateY = 0;

  switch (config.entranceAnimation) {
    case "spring": {
      const prog = spring({
        frame,
        fps,
        config: { mass: 0.8, stiffness: 200, damping: 15 },
        durationInFrames: 20,
      });
      animScale = interpolate(prog, [0, 1], [0.7, 1]);
      animOpacity = interpolate(prog, [0, 1], [0, 1]);
      break;
    }
    case "fade": {
      animOpacity = interpolate(frame, [0, 15], [0, 1], {
        extrapolateRight: "clamp",
      });
      break;
    }
    case "slide-up": {
      const prog = spring({
        frame,
        fps,
        config: { mass: 1, stiffness: 150, damping: 18 },
        durationInFrames: 20,
      });
      animTranslateY = interpolate(prog, [0, 1], [60, 0]);
      animOpacity = interpolate(prog, [0, 1], [0, 1]);
      break;
    }
    default:
      break;
  }

  // Exit fade (last 15 frames)
  const fadeOutStart = displayFrames - 15;
  if (frame > fadeOutStart) {
    animOpacity *= interpolate(frame, [fadeOutStart, displayFrames], [1, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
  }

  const positionStyle = POSITION_STYLE[config.position] ?? POSITION_STYLE.top;
  const look = HOOK_LOOKS[config.style ?? "classic"] ?? HOOK_LOOKS.classic;

  // Base font size: 5% of 1080 width (matches hooks.py logic)
  const baseFontSize = 1080 * 0.05;
  const fontSize = Math.round(baseFontSize * scale);
  const outlinePx = Math.round(look.outlinePx * scale);

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
          opacity: animOpacity,
          transform: `scale(${animScale}) translateY(${animTranslateY}px)`,
          maxWidth: "90%",
          backgroundColor: look.box ?? "transparent",
          borderRadius: 20,
          padding: look.box ? `${25 * scale}px ${30 * scale}px` : 0,
          boxShadow: look.shadow ? "5px 5px 15px rgba(0, 0, 0, 0.25)" : "none",
          textAlign: "center",
        }}
      >
        <span
          style={{
            fontFamily: `'${NOTO_SERIF_FONT_FAMILY}', 'Noto Serif', Georgia, serif`,
            fontSize,
            fontWeight: 700,
            color: look.text,
            lineHeight: 1.4,
            wordBreak: "break-word",
            ...(outlinePx > 0
              ? {
                  WebkitTextStroke: `${outlinePx}px #000000`,
                  paintOrder: "stroke fill",
                }
              : {}),
          }}
        >
          {config.text}
        </span>
      </div>
    </div>
  );
};
