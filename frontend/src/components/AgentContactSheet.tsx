import React from 'react';
import {
  Modal, View, Text, StyleSheet, TouchableOpacity,
  Linking, Platform, Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS } from '../lib/auth';

export interface AgentContact {
  name: string;
  role: string;
  io_role?: string;
  phone?: string;
  email?: string;
  office?: string;
}

interface Props {
  agent: AgentContact | null;
  onClose: () => void;
}

const IO_ROLE_LABEL: Record<string, string> = {
  RGA: 'RGA', MGA: 'MGA', GA: 'GA', SA: 'SA',
  Agent: 'Agent', Builder: 'Builder', inTraining: 'In Training',
};

export function formatPhone(raw: string | undefined | null): string {
  if (!raw) return '';
  const d = raw.replace(/\D/g, '');
  if (d.length === 10) return `(${d.slice(0, 3)}) ${d.slice(3, 6)}-${d.slice(6)}`;
  return raw;
}

function openLink(url: string, errorMessage: string) {
  Linking.openURL(url).catch((err) => {
    console.error('Failed to open link', err);
    Alert.alert('Error', errorMessage);
  });
}

export function AgentContactSheet({ agent, onClose }: Props) {
  if (!agent) return null;

  const label = agent.io_role ? (IO_ROLE_LABEL[agent.io_role] ?? agent.io_role) : agent.role.replace('level_', 'L');

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.container}>
      <TouchableOpacity style={styles.backdrop} activeOpacity={1} onPress={onClose} />
      <View style={styles.sheet}>
        <View style={styles.handle} />

        <Text style={styles.name}>{agent.name}</Text>
        <View style={styles.badgeRow}>
          <View style={styles.badge}><Text style={styles.badgeTxt}>{label}</Text></View>
          {agent.office ? <Text style={styles.office}>{agent.office}</Text> : null}
        </View>

        {agent.phone ? (
          <TouchableOpacity
            style={styles.contactRow}
            onPress={() => openLink(`tel:${agent.phone!.replace(/\D/g, '')}`, 'Could not open the phone dialer.')}
            activeOpacity={0.7}
          >
            <View style={styles.iconWrap}>
              <Ionicons name="call" size={18} color={COLORS.primary} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.contactLabel}>CALL</Text>
              <Text style={styles.contactValue}>{formatPhone(agent.phone)}</Text>
            </View>
            <Ionicons name="chevron-forward" size={16} color={COLORS.textDim} />
          </TouchableOpacity>
        ) : null}

        {agent.phone ? (
          <TouchableOpacity
            style={styles.contactRow}
            onPress={() => openLink(`sms:${agent.phone!.replace(/\D/g, '')}`, 'Could not open the SMS app.')}
            activeOpacity={0.7}
          >
            <View style={styles.iconWrap}>
              <Ionicons name="chatbubble" size={18} color={COLORS.secondary} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.contactLabel}>TEXT</Text>
              <Text style={styles.contactValue}>{formatPhone(agent.phone)}</Text>
            </View>
            <Ionicons name="chevron-forward" size={16} color={COLORS.textDim} />
          </TouchableOpacity>
        ) : null}

        {agent.email ? (
          <TouchableOpacity
            style={styles.contactRow}
            onPress={() => openLink(`mailto:${agent.email}`, 'Could not open the mail app.')}
            activeOpacity={0.7}
          >
            <View style={styles.iconWrap}>
              <Ionicons name="mail" size={18} color={COLORS.gold} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.contactLabel}>EMAIL</Text>
              <Text style={styles.contactValue}>{agent.email}</Text>
            </View>
            <Ionicons name="chevron-forward" size={16} color={COLORS.textDim} />
          </TouchableOpacity>
        ) : null}

        <TouchableOpacity style={styles.closeBtn} onPress={onClose}>
          <Text style={styles.closeTxt}>CLOSE</Text>
        </TouchableOpacity>
      </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  backdrop: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0,0,0,0.6)',
  },
  sheet: {
    backgroundColor: '#1A1A1A',
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    padding: 20,
    paddingBottom: Platform.OS === 'ios' ? 36 : 24,
    borderTopWidth: 2,
    borderTopColor: COLORS.primary,
  },
  handle: {
    width: 36,
    height: 4,
    backgroundColor: COLORS.border,
    borderRadius: 2,
    alignSelf: 'center',
    marginBottom: 16,
  },
  name: {
    color: '#fff',
    fontWeight: '900',
    fontSize: 20,
    marginBottom: 6,
  },
  badgeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 20,
  },
  badge: {
    backgroundColor: 'rgba(49,152,66,0.18)',
    borderWidth: 1,
    borderColor: COLORS.primary,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 3,
  },
  badgeTxt: {
    color: COLORS.primary,
    fontWeight: '900',
    fontSize: 11,
    letterSpacing: 1,
  },
  office: {
    color: COLORS.textDim,
    fontSize: 12,
  },
  contactRow: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: COLORS.surface,
    borderWidth: 1,
    borderColor: COLORS.border,
    borderRadius: 8,
    padding: 14,
    marginBottom: 8,
    gap: 12,
  },
  iconWrap: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: COLORS.surface2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  contactLabel: {
    color: COLORS.textDim,
    fontSize: 9,
    fontWeight: '900',
    letterSpacing: 1.5,
    marginBottom: 2,
  },
  contactValue: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '700',
  },
  closeBtn: {
    marginTop: 8,
    paddingVertical: 14,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: COLORS.border,
    borderRadius: 8,
  },
  closeTxt: {
    color: COLORS.textDim,
    fontWeight: '900',
    fontSize: 12,
    letterSpacing: 1.5,
  },
});
