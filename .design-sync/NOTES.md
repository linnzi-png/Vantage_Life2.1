# Design Sync Notes — VantageLife Design System

## Shape
This is a `tokens-only` sync — not a full component library. VantageLife is a React Native / Expo mobile app; the components use RN primitives (`View`, `Text`, `StyleSheet`) and cannot be bundled as web components. The sync uploads CSS custom properties and design guidelines only.

## What's uploaded
- `styles.css` — generated CSS custom property file with all tokens + utility classes
- `README.md` — quick reference
- `guidelines/design-system.md` — full DESIGN_SYSTEM.md content
- `guidelines/component-specs.md` — full COMPONENT_SPECS.md content

## Re-sync risks
- `styles.css` was hand-authored from `DESIGN_SYSTEM.md` and `design_guidelines.json`. If either changes, re-sync must update `ds-bundle/styles.css` manually (or re-run this skill and regenerate it).
- No `_ds_sync.json` anchor — future re-syncs will re-upload everything; there's nothing to diff.
- No live component previews. The design agent has textual specs only, not rendered components.

## Future upgrade path
If the team builds a web component layer (e.g., via react-native-web wrappers with a proper esbuild entry), the standard storybook or package shape can be used for a full component sync at that point.
