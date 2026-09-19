// Display typography. The design guidelines name Barlow Condensed for
// headings, but the app has never loaded a custom face; every screen sits on
// the system font. The Push Month card is the first place it is used (owner,
// 2026-09-19): one family, two weights, loaded through expo-font.
//
// Loading is never blocking. Screens read `loaded` and fall back to the
// system font until the files are in, so a slow first launch shows the card
// a beat early on the wrong face rather than not at all. Weight is carried
// by the file, so callers set fontFamily and leave fontWeight alone — on
// Android a synthetic fontWeight on a custom family can fall back to the
// system face.
import {
  useFonts,
  BarlowCondensed_600SemiBold,
  BarlowCondensed_800ExtraBold,
} from '@expo-google-fonts/barlow-condensed';

export const DISPLAY_FONT = {
  semibold: 'BarlowCondensed_600SemiBold',
  extrabold: 'BarlowCondensed_800ExtraBold',
} as const;

const DISPLAY_FONT_FILES = {
  [DISPLAY_FONT.semibold]: BarlowCondensed_600SemiBold,
  [DISPLAY_FONT.extrabold]: BarlowCondensed_800ExtraBold,
};

/** True once the display faces are usable. Safe to call from several
 *  components at once: expo-font loads each file once and answers the rest
 *  from cache. */
export function useDisplayFonts(): boolean {
  const [loaded] = useFonts(DISPLAY_FONT_FILES);
  return loaded;
}
