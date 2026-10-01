// Shared test setup. Components pull COLORS and api() from src/lib/auth.tsx,
// which pulls AsyncStorage, expo-router and the push registration at import
// time; none of those exist under Jest, so they are replaced here once
// rather than in every test file.

// The package ships its own Jest mock; jest.mock needs the factory to resolve
// it synchronously, which is what require() is for here.
// eslint-disable-next-line @typescript-eslint/no-require-imports
jest.mock('@react-native-async-storage/async-storage', () => require('@react-native-async-storage/async-storage/jest/async-storage-mock'));

jest.mock('expo-router', () => ({
  router: { push: jest.fn(), replace: jest.fn(), back: jest.fn() },
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), back: jest.fn() }),
  useFocusEffect: jest.fn(),
  useLocalSearchParams: () => ({}),
  usePathname: () => '/',
}));

// Reanimated 4 drives its animations through the native Worklets runtime,
// which does not exist under Jest. Both packages ship a JS mock for this.
jest.mock('react-native-worklets', () => require('react-native-worklets/lib/module/mock'));
jest.mock('react-native-reanimated', () => require('react-native-reanimated/mock'));

// Liquid Glass is a native iOS 26 view with no JS fallback under Jest. The
// gate says "unavailable", so every glass surface draws its plain version, and
// the glass components themselves are pass-through views.
jest.mock('expo-glass-effect', () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { View } = require('react-native');
  return {
    GlassView: View,
    GlassContainer: View,
    isLiquidGlassAvailable: () => false,
    isGlassEffectAPIAvailable: () => false,
  };
});

jest.mock('./src/lib/push', () => ({
  registerForPulseNotifications: jest.fn(async () => null),
}));
