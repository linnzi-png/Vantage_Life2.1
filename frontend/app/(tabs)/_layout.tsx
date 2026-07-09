import React from 'react';
import { Tabs } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { COLORS, useAuth, levelNum } from '../../src/lib/auth';

export default function TabsLayout() {
  const { user } = useAuth();
  const lvl = levelNum(user?.role);
  const insets = useSafeAreaInsets();

  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: COLORS.bg },
        headerTitleStyle: { color: '#fff', fontWeight: '900', letterSpacing: 1.2 },
        headerShadowVisible: false,
        // Fixed height ignored the home-indicator inset, clipping labels on
        // bezel-less iPhones; grow the bar by the inset instead.
        tabBarStyle: { backgroundColor: '#000', borderTopColor: COLORS.border, height: 60 + insets.bottom, paddingBottom: 8 + insets.bottom, paddingTop: 6 },
        tabBarActiveTintColor: COLORS.primary,
        tabBarInactiveTintColor: COLORS.textDim,
        tabBarLabelStyle: { fontSize: 10, fontWeight: '800', letterSpacing: 0.5 },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{ title: 'DASHBOARD', tabBarIcon: ({ color, size }) => <Ionicons name="speedometer" size={size} color={color} /> }}
      />
      <Tabs.Screen
        name="pulse"
        options={{ title: 'PULSE', tabBarIcon: ({ color, size }) => <Ionicons name="pulse" size={size} color={color} /> }}
      />
      <Tabs.Screen
        name="shoutouts"
        options={{ title: 'SHOUTOUTS', tabBarIcon: ({ color, size }) => <Ionicons name="megaphone" size={size} color={color} /> }}
      />
      <Tabs.Screen
        name="team"
        options={{
          title: 'TEAM',
          headerShown: false,
          tabBarIcon: ({ color, size }) => <Ionicons name="people" size={size} color={color} />,
          href: lvl >= 2 ? undefined : null,
        }}
      />
      <Tabs.Screen
        name="more"
        options={{ title: 'MORE', tabBarIcon: ({ color, size }) => <Ionicons name="grid" size={size} color={color} /> }}
      />
    </Tabs>
  );
}
