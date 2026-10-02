import { z } from "zod";

// --- Word-level caption ---
export interface CaptionWord {
  text: string;
  startMs: number;
  endMs: number;
}

// --- Subtitle config ---
export type SubtitleAnimation =
  | "none"
  | "word-highlight"
  | "pop"
  | "karaoke"
  | "box"
  | "highlight-box";
// 0-100, % of frame height up from the bottom (matches subtitles.py's
// position_percent) — a slider value, not a fixed preset. The legacy string
// presets still work for any older config that hasn't been re-saved.
export type SubtitlePosition = number | "top" | "middle" | "bottom";

export interface SubtitleStyle {
  fontFamily: string;
  fontSize: number;
  fontColor: string;
  highlightColor: string;
  borderColor: string;
  borderWidth: number;
  bgColor: string;
  bgOpacity: number;
  animation: SubtitleAnimation;
  // Anton has a single weight and libass does not synthesise a bold for it,
  // so the preview must not ask for 700 there either (see assScale.ts).
  fontWeight?: number;
  // Karaoke look: dim inactive words (0-1) and force uppercase.
  baseOpacity?: number;
  uppercase?: boolean;
  // ASS "Spacing" equivalent, in px — positive tracks letters apart.
  letterSpacing?: number;
}

export interface SubtitleConfig {
  captions: CaptionWord[];
  position: SubtitlePosition;
  style: SubtitleStyle;
  // Caption-block chunking, mirrored from subtitles.py's own defaults so the
  // preview groups words the same way the real burn does.
  maxChars?: number;
  maxDurationMs?: number;
  maxWords?: number | null;
}

// --- Hook config ---
export type HookPosition = "top" | "center" | "bottom";
export type HookSize = "S" | "M" | "L";
export type HookEntrance = "spring" | "fade" | "slide-up" | "none";
export type HookStyle =
  | "classic"
  | "dark"
  | "yellow"
  | "red"
  | "outline"
  | "outline_yellow"
  | "bold"
  | "docline";

export interface HookConfig {
  text: string;
  position: HookPosition;
  size: HookSize;
  style?: HookStyle;
  entranceAnimation: HookEntrance;
  displayDurationSec: number;
}

// --- Effects config ---
export interface EffectSegment {
  startSec: number;
  endSec: number;
  zoom: number;
  zoomCenterX: number;
  zoomCenterY: number;
  brightness: number;
  contrast: number;
  saturate: number;
}

export interface EffectsConfig {
  segments: EffectSegment[];
}

// --- Main composition props ---
export interface ShortVideoProps {
  videoUrl: string;
  durationInFrames: number;
  fps: number;
  width: number;
  height: number;
  subtitles: SubtitleConfig | null;
  hook: HookConfig | null;
  effects: EffectsConfig | null;
}

// --- Zod schemas for validation (used by render service) ---
export const captionWordSchema = z.object({
  text: z.string(),
  startMs: z.number(),
  endMs: z.number(),
});

export const subtitleStyleSchema = z.object({
  fontFamily: z.string(),
  fontSize: z.number(),
  fontColor: z.string(),
  highlightColor: z.string(),
  borderColor: z.string(),
  borderWidth: z.number(),
  bgColor: z.string(),
  bgOpacity: z.number().min(0).max(1),
  animation: z.enum(["none", "word-highlight", "pop", "karaoke", "box", "highlight-box"]),
  fontWeight: z.number().optional(),
});

export const subtitleConfigSchema = z.object({
  captions: z.array(captionWordSchema),
  position: z.union([z.number(), z.enum(["top", "middle", "bottom"])]),
  style: subtitleStyleSchema,
  maxChars: z.number().optional(),
  maxDurationMs: z.number().optional(),
  maxWords: z.number().nullable().optional(),
});

export const hookConfigSchema = z.object({
  text: z.string(),
  position: z.enum(["top", "center", "bottom"]),
  size: z.enum(["S", "M", "L"]),
  style: z
    .enum(["classic", "dark", "yellow", "red", "outline", "outline_yellow", "bold", "docline"])
    .default("classic"),
  entranceAnimation: z.enum(["spring", "fade", "slide-up", "none"]),
  displayDurationSec: z.number().positive(),
});

export const effectSegmentSchema = z.object({
  startSec: z.number().min(0),
  endSec: z.number().positive(),
  zoom: z.number().min(0.5).max(3),
  zoomCenterX: z.number().min(0).max(1),
  zoomCenterY: z.number().min(0).max(1),
  brightness: z.number().min(0).max(3),
  contrast: z.number().min(0).max(3),
  saturate: z.number().min(0).max(3),
});

export const effectsConfigSchema = z.object({
  segments: z.array(effectSegmentSchema),
});

export const shortVideoPropsSchema = z.object({
  videoUrl: z.string(),
  durationInFrames: z.number().int().positive(),
  fps: z.number().positive(),
  width: z.number().int().positive(),
  height: z.number().int().positive(),
  subtitles: subtitleConfigSchema.nullable(),
  hook: hookConfigSchema.nullable(),
  effects: effectsConfigSchema.nullable(),
});
