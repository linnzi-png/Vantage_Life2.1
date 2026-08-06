// Guided-walkthrough spotlight overlay. Rendered once at the root; navigates
// the real app between steps and highlights the registered anchor for the
// current one. Must be a <Modal>: a root-mounted absolute View would render
// behind native modals on iOS, and the tour deliberately never opens the
// app's own sheets, so nothing ever sits above this overlay during a step.
import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Keyboard,
  Modal,
  Platform,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  useWindowDimensions,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { router, usePathname } from 'expo-router';
import * as Haptics from 'expo-haptics';
import { COLORS } from '../lib/auth';
import { useTour } from '../lib/tour';

interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

const TAB_BAR_BASE = 60; // matches tabBarStyle height in app/(tabs)/_layout.tsx
const MEASURE_DELAY = 300; // let the fade route transition settle first
const MEASURE_INTERVAL = 150;
const MEASURE_TIMEOUT = 2000;
const FRAME_PAD = 6;
const CARD_MARGIN = 16;
const CARD_MAX_WIDTH = 380;
const SCRIM = 'rgba(0,0,0,0.78)';

function buzz() {
  if (Platform.OS !== 'web') {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
  }
}

export function TourOverlay() {
  const { active, steps, index, next, back, skip, finish, getAnchor } = useTour();
  const pathname = usePathname();
  const { width: winW, height: winH } = useWindowDimensions();
  const insets = useSafeAreaInsets();

  const step = active && index < steps.length ? steps[index] : null;
  const isLast = index >= steps.length - 1;

  // null while measuring; then either the anchor's rect or a fallback flag.
  const [rect, setRect] = useState<Rect | null>(null);
  const [settled, setSettled] = useState(false);
  const [cardH, setCardH] = useState(0);

  // Route to the current step's screen.
  useEffect(() => {
    if (step && pathname !== step.screen) router.navigate(step.screen);
  }, [step, pathname]);

  // Measure the current step's anchor once its screen is up.
  useEffect(() => {
    setRect(null);
    setSettled(false);
    if (!step || pathname !== step.screen) return;
    Keyboard.dismiss(); // e.g. the Pulse input auto-focuses
    if (step.anchor === null) {
      setSettled(true);
      return;
    }
    if (step.anchor === 'tabbar') {
      const h = TAB_BAR_BASE + insets.bottom;
      setRect({ x: 0, y: winH - h, width: winW, height: h });
      setSettled(true);
      return;
    }
    const anchorId = step.anchor;
    let cancelled = false;
    let elapsed = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const schedule = () => {
      elapsed += MEASURE_INTERVAL;
      if (elapsed >= MEASURE_TIMEOUT) {
        // Anchor absent (empty state / conditional render) — centered card.
        setSettled(true);
        return;
      }
      timer = setTimeout(tick, MEASURE_INTERVAL);
    };
    const tick = () => {
      if (cancelled) return;
      const node = getAnchor(anchorId);
      if (!node) {
        schedule();
        return;
      }
      node.measureInWindow((x, y, width, height) => {
        if (cancelled) return;
        if (!(width > 0 && height > 0)) {
          schedule();
          return;
        }
        // A target scrolled out of view won't scroll itself back — fall
        // straight through to the centered card instead of spotlighting
        // something offscreen.
        const visible = y < winH && y + height > 0 && x < winW && x + width > 0;
        if (visible) setRect({ x, y, width, height });
        setSettled(true);
      });
    };
    timer = setTimeout(tick, MEASURE_DELAY);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [step, pathname, winW, winH, insets.bottom, getAnchor]);

  const onNext = useCallback(() => {
    buzz();
    if (isLast) finish();
    else next();
  }, [isLast, finish, next]);

  const onBack = useCallback(() => {
    buzz();
    back();
  }, [back]);

  // Android hardware back / web ESC. Alert.alert is a no-op on web, so skip
  // directly there.
  const confirmSkip = useCallback(() => {
    if (Platform.OS === 'web') {
      skip();
      return;
    }
    Alert.alert('Skip walkthrough?', 'You can replay it anytime from MORE → App Walkthrough.', [
      { text: 'Keep going', style: 'cancel' },
      { text: 'Skip', style: 'destructive', onPress: skip },
    ]);
  }, [skip]);

  if (!step) return null;

  const frame: Rect | null = rect
    ? {
        x: rect.x - FRAME_PAD,
        y: rect.y - FRAME_PAD,
        width: rect.width + FRAME_PAD * 2,
        height: rect.height + FRAME_PAD * 2,
      }
    : null;

  const cardWidth = Math.min(winW - CARD_MARGIN * 2, CARD_MAX_WIDTH);
  let cardTop = 0;
  let cardLeft = CARD_MARGIN;
  if (frame) {
    const estH = cardH || 220;
    const below = frame.y + frame.height + 12;
    const fitsBelow = below + estH + 12 <= winH;
    const placeBelow = step.placement === 'below' || (step.placement !== 'above' && fitsBelow);
    cardTop = placeBelow ? below : Math.max(insets.top + 12, frame.y - estH - 12);
    const centerX = frame.x + frame.width / 2;
    cardLeft = Math.min(Math.max(centerX - cardWidth / 2, CARD_MARGIN), winW - cardWidth - CARD_MARGIN);
  }

  const card = (
    <View
      style={[
        styles.card,
        { width: cardWidth },
        frame ? { position: 'absolute', top: cardTop, left: cardLeft } : null,
      ]}
      onLayout={(e) => setCardH(e.nativeEvent.layout.height)}
      testID="tour-card"
    >
      <Text style={styles.kicker}>
        STEP {index + 1} OF {steps.length}
      </Text>
      <Text style={styles.title}>{step.title}</Text>
      <Text style={styles.body}>{step.body}</Text>
      <View style={styles.btnRow}>
        {index > 0 ? (
          <TouchableOpacity style={[styles.btn, styles.btnGhost]} onPress={onBack} testID="tour-back">
            <Text style={styles.btnGhostTxt}>BACK</Text>
          </TouchableOpacity>
        ) : (
          <View style={{ flex: 1 }} />
        )}
        <TouchableOpacity style={[styles.btn, styles.btnPrimary]} onPress={onNext} testID="tour-next">
          <Text style={styles.btnPrimaryTxt}>{isLast ? 'FINISH' : 'NEXT'}</Text>
        </TouchableOpacity>
      </View>
      <TouchableOpacity onPress={skip} style={styles.skipBtn} testID="tour-skip">
        <Text style={styles.skipTxt}>SKIP TOUR</Text>
      </TouchableOpacity>
    </View>
  );

  return (
    <Modal visible={active} transparent statusBarTranslucent animationType="fade" onRequestClose={confirmSkip}>
      <View style={styles.root} testID="tour-overlay">
        {frame ? (
          <>
            {/* Scrim with a spotlight cutout: four strips around the frame. */}
            <View style={[styles.scrim, { top: 0, left: 0, right: 0, height: Math.max(frame.y, 0) }]} />
            <View style={[styles.scrim, { top: frame.y + frame.height, left: 0, right: 0, bottom: 0 }]} />
            <View style={[styles.scrim, { top: frame.y, left: 0, width: Math.max(frame.x, 0), height: frame.height }]} />
            <View style={[styles.scrim, { top: frame.y, left: frame.x + frame.width, right: 0, height: frame.height }]} />
            <View
              pointerEvents="none"
              style={[
                styles.frame,
                { top: frame.y, left: frame.x, width: frame.width, height: frame.height },
              ]}
            />
            {settled ? card : null}
          </>
        ) : (
          <View style={styles.centerWrap}>{settled ? card : null}</View>
        )}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  scrim: { position: 'absolute', backgroundColor: SCRIM },
  frame: { position: 'absolute', borderWidth: 2, borderColor: COLORS.gold, borderRadius: 8 },
  centerWrap: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: SCRIM,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
  },
  card: {
    backgroundColor: COLORS.surface,
    borderWidth: 1,
    borderColor: COLORS.border,
    borderTopWidth: 2,
    borderTopColor: COLORS.primary,
    borderRadius: 6,
    padding: 16,
  },
  kicker: { color: COLORS.textDim, fontSize: 10, fontWeight: '900', letterSpacing: 2 },
  title: { color: '#fff', fontSize: 18, fontWeight: '900', marginTop: 6, letterSpacing: 0.5 },
  body: { color: COLORS.textDim, fontSize: 13, lineHeight: 19, marginTop: 8 },
  btnRow: { flexDirection: 'row', gap: 8, marginTop: 14 },
  btn: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 4,
    alignItems: 'center',
    justifyContent: 'center',
    flexDirection: 'row',
    gap: 6,
  },
  btnPrimary: { backgroundColor: COLORS.primary },
  btnPrimaryTxt: { color: '#000', fontWeight: '900', letterSpacing: 1 },
  btnGhost: { borderWidth: 1, borderColor: COLORS.border, backgroundColor: 'transparent' },
  btnGhostTxt: { color: COLORS.textDim, fontWeight: '900', letterSpacing: 1 },
  skipBtn: { alignSelf: 'center', marginTop: 12, paddingHorizontal: 8, paddingVertical: 2 },
  skipTxt: { color: COLORS.textMuted, fontSize: 10, fontWeight: '900', letterSpacing: 1.5 },
});
