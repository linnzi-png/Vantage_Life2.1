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

jest.mock('./src/lib/push', () => ({
  registerForPulseNotifications: jest.fn(async () => null),
}));
