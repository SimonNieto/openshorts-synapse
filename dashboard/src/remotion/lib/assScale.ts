/**
 * Editor value -> preview pixel conversions, measured against the real burn.
 *
 * subtitles.generate_ass writes an ASS script with PlayResY=288 and libass
 * scales that script onto the 1080x1920 output. Measured on that output
 * (Anton, font sizes 44 and 80, border widths 0/2/4/5), libass does NOT use
 * one factor for everything:
 *   - glyphs scale by  1080/288 = 3.75 px per ASS unit
 *   - outlines scale by 1920/288 = 6.67 px per ASS unit
 *
 * The preview composition is that same 1080x1920 frame, so it has to apply
 * the same factors or it shows a different size than the file it claims to
 * preview. The values here replace flat *2.2 / *1.5 fudge factors that were
 * never derived from the burn: captions rendered ~45% too small in the editor
 * with an outline ~4x too thin, which is why a clip came back "much bigger"
 * than what the editor had shown.
 */
export const ASS_GLYPH_PX = 1080 / 288;
export const ASS_OUTLINE_PX = 1920 / 288;

/** generate_ass's own `final_fontsize = fontsize * 0.85`. */
export const ASS_FONTSIZE_FACTOR = 0.85;

export function previewFontSizePx(fontSize: number): number {
  return fontSize * ASS_FONTSIZE_FACTOR * ASS_GLYPH_PX;
}

export function previewBorderPx(borderWidth: number): number {
  return borderWidth * ASS_OUTLINE_PX;
}

export function previewLetterSpacingPx(letterSpacing: number): number {
  return letterSpacing * ASS_GLYPH_PX;
}

/**
 * Anton ships in a single weight, and libass does not widen it for Bold=1
 * (measured: the burned advance matches the plain face). Asking the browser
 * for 700 there would trigger synthetic bolding and draw fatter text than the
 * clip. The Liberation faces the other picker names map to ARE the bold cuts,
 * so they keep 700.
 */
export function previewFontWeight(fontName: string): number {
  const n = String(fontName || '').trim().toLowerCase();
  return n === 'anton' || n === 'impact' ? 400 : 700;
}
