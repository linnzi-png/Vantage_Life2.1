// More tab: profile, manager, audit, vault, logout
import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useAuth, COLORS, levelNum } from '../../src/lib/auth';

export default function MoreScreen() {
  const router = useRouter();
  const { user, agent, roleLabel, signOut, deleteAccount } = useAuth();
  const lvl = levelNum(user?.role);

  const items: { id: string; icon: any; label: string; onPress: () => void; show: boolean }[] = [
    { id: 'manager', icon: 'construct', label: 'Manager Command Panel', onPress: () => router.push('/manager'), show: lvl >= 4 },
    { id: 'audit', icon: 'list', label: 'Audit Log', onPress: () => router.push('/audit'), show: lvl >= 4 },
    { id: 'vault', icon: 'archive', label: 'Historical Vault', onPress: () => router.push('/vault'), show: lvl >= 4 },
  ];

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <ScrollView contentContainerStyle={{ padding: 16 }}>
        <View style={styles.profile} testID="profile-card">
          <View style={styles.avatar}><Text style={styles.avatarTxt}>{(user?.name || '?').slice(0, 1)}</Text></View>
          <View style={{ flex: 1, marginLeft: 12 }}>
            <Text style={styles.name}>{user?.name}</Text>
            <Text style={styles.email}>{user?.email}</Text>
            <View style={styles.roleRow}>
              <Text style={styles.role}>{roleLabel}</Text>
              {agent ? <Text style={styles.dot}> · </Text> : null}
              {agent ? <Text style={styles.office}>{agent.office}</Text> : null}
            </View>
          </View>
        </View>

        {items.filter((i) => i.show).length > 0 ? (
          <>
            <Text style={styles.kicker}>EXECUTIVE TOOLS</Text>
            <View style={styles.list}>
              {items.filter((i) => i.show).map((it) => (
                <TouchableOpacity key={it.id} style={styles.item} onPress={it.onPress} testID={`more-${it.id}`}>
                  <Ionicons name={it.icon} size={18} color={COLORS.primary} />
                  <Text style={styles.itemTxt}>{it.label}</Text>
                  <Ionicons name="chevron-forward" size={16} color={COLORS.textDim} />
                </TouchableOpacity>
              ))}
            </View>
          </>
        ) : null}

        <Text style={[styles.kicker, { marginTop: 16 }]}>ACCOUNT</Text>
        <View style={styles.list}>
          <TouchableOpacity style={styles.item} onPress={async () => { await signOut(); router.replace('/login'); }} testID="logout-btn">
            <Ionicons name="log-out" size={18} color={COLORS.red} />
            <Text style={[styles.itemTxt, { color: COLORS.red }]}>Sign Out</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.item}
            testID="delete-account-btn"
            onPress={() => {
              Alert.alert(
                'Delete Account',
                'This will permanently delete your account and all associated data. This cannot be undone.',
                [
                  { text: 'Cancel', style: 'cancel' },
                  {
                    text: 'Delete My Account',
                    style: 'destructive',
                    onPress: () => {
                      Alert.alert(
                        'Are you sure?',
                        'Type "DELETE" to confirm permanent account deletion.',
                        [
                          { text: 'Cancel', style: 'cancel' },
                          {
                            text: 'Permanently Delete',
                            style: 'destructive',
                            onPress: async () => {
                              try {
                                await deleteAccount();
                                router.replace('/login');
                              } catch (e: unknown) {
                                Alert.alert('Error', e instanceof Error ? e.message : 'Account deletion failed.');
                              }
                            },
                          },
                        ],
                      );
                    },
                  },
                ],
              );
            }}
          >
            <Ionicons name="trash" size={18} color={COLORS.red} />
            <Text style={[styles.itemTxt, { color: COLORS.red }]}>Delete Account</Text>
          </TouchableOpacity>
        </View>

        <Text style={styles.footer}>VantageLife 2.0 · AO Premiere · America/Detroit</Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.bg },
  profile: { flexDirection: 'row', alignItems: 'center', backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderTopColor: COLORS.primary, borderTopWidth: 2, padding: 14, borderRadius: 6 },
  avatar: { width: 48, height: 48, borderRadius: 4, backgroundColor: COLORS.primary, alignItems: 'center', justifyContent: 'center' },
  avatarTxt: { color: '#000', fontWeight: '900', fontSize: 22 },
  name: { color: '#fff', fontWeight: '900', fontSize: 16 },
  email: { color: COLORS.textDim, fontSize: 12, marginTop: 2 },
  roleRow: { flexDirection: 'row', alignItems: 'center', marginTop: 4 },
  role: { color: COLORS.primary, fontWeight: '900', fontSize: 11, letterSpacing: 1.4 },
  office: { color: COLORS.textDim, fontSize: 11 },
  dot: { color: COLORS.textDim },
  kicker: { color: COLORS.textDim, fontWeight: '900', fontSize: 11, letterSpacing: 2, marginVertical: 12 },
  list: { gap: 1, backgroundColor: COLORS.border, borderRadius: 6, overflow: 'hidden' },
  item: { flexDirection: 'row', alignItems: 'center', backgroundColor: COLORS.surface, padding: 14, gap: 12 },
  itemTxt: { color: '#fff', fontWeight: '700', fontSize: 14, flex: 1 },
  logout: { flexDirection: 'row', alignItems: 'center', gap: 10, padding: 14, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: 6 },
  logoutTxt: { color: COLORS.red, fontWeight: '800' },
  footer: { color: COLORS.textMuted, fontSize: 10, textAlign: 'center', marginTop: 24 },
});
