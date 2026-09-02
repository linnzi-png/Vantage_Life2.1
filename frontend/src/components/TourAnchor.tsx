// Registers its View as a guided-walkthrough spotlight target. Replace an
// existing container View with <TourAnchor id=... style=...> (layout-neutral),
// or wrap a component that doesn't forward refs.
import React, { ReactNode, useCallback } from 'react';
import { LayoutChangeEvent, StyleProp, View, ViewStyle } from 'react-native';
import { useTour } from '../lib/tour';
import { TourAnchorId } from '../lib/tourSteps';

interface Props {
  id: TourAnchorId;
  style?: StyleProp<ViewStyle>;
  testID?: string;
  onLayout?: (e: LayoutChangeEvent) => void;
  children?: ReactNode;
}

export function TourAnchor({ id, style, testID, onLayout, children }: Props) {
  const { registerAnchor } = useTour();
  // Callback ref: registers on mount, unregisters on unmount (node === null).
  const refCb = useCallback((node: View | null) => registerAnchor(id, node), [id, registerAnchor]);
  return (
    // collapsable={false} keeps Android from flattening the View, which would
    // make measureInWindow report zeros.
    <View ref={refCb} collapsable={false} style={style} testID={testID} onLayout={onLayout}>
      {children}
    </View>
  );
}
