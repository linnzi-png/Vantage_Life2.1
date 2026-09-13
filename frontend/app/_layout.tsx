import React, { useEffect } from 'react';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import * as SplashScreen from 'expo-splash-screen';
import { AuthProvider } from '../src/lib/auth';
import { TourProvider } from '../src/lib/tour';
import { TourOverlay } from '../src/components/TourOverlay';
import NotificationNagOverlay from '../src/components/NotificationNagOverlay';
import { ErrorBoundary } from '../src/components/ErrorBoundary';

// Keep the splash visible until the layout tree is mounted.
// Without this, the splash auto-hides before React has painted the dark
// background, producing a white flash on every cold start and post-auth
// navigation.
SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  useEffect(() => {
    // Hide once the root layout has rendered.  Auth state is still loading
    // at this point, but the dark GestureHandlerRootView is already on screen,
    // so there is nothing white to see between splash dismiss and content.
    SplashScreen.hideAsync();
  }, []);

  return (
    <GestureHandlerRootView style={{ flex: 1, backgroundColor: '#0D0D0D' }}>
      <SafeAreaProvider>
        <AuthProvider>
          {/* Inside AuthProvider on purpose: a render throw in a screen shows
              the recovery card while the session stays loaded, so TRY AGAIN
              re-mounts the screen rather than signing the agent back in. */}
          <ErrorBoundary>
          <TourProvider>
            <StatusBar style="light" />
            <Stack
              screenOptions={{
                headerStyle: { backgroundColor: '#0D0D0D' },
                headerTintColor: '#FFFFFF',
                // Dark background on every screen so no white bleeds through
                // during the login → tabs transition.
                contentStyle: { backgroundColor: '#0D0D0D' },
                headerShadowVisible: false,
                // 'fade' crossfade eliminates the white flash that 'slide'
                // and the default transition show between screens.
                animation: 'fade',
              }}
            >
              <Stack.Screen name="index" options={{ headerShown: false }} />
              <Stack.Screen name="login" options={{ headerShown: false }} />
              <Stack.Screen name="pending" options={{ headerShown: false }} />
              <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
              <Stack.Screen name="manager" options={{ title: 'Manager Command' }} />
              <Stack.Screen name="audit" options={{ title: 'Audit Log' }} />
              <Stack.Screen name="vault" options={{ title: 'Historical Vault' }} />
              <Stack.Screen name="push-log" options={{ title: 'Push Delivery Log' }} />
              <Stack.Screen name="admin" options={{ title: 'Admin Panel' }} />
            </Stack>
            <TourOverlay />
            <NotificationNagOverlay />
          </TourProvider>
          </ErrorBoundary>
        </AuthProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
