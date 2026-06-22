import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Linking, Modal, Pressable } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS } from '../lib/auth';

export interface AgentContact {
  name: string;
  role: string;
  phone?: string;
  email?: string;
  office: string;
}

interface Props {
  agent: AgentContact | null;
  onClose: () => void;
}

export function AgentContactSheet({ agent, onClose }: Props) {
  if (!agent) return null;

  const roleLabel = agent.role.replace('level_', 'L').toUpperCase();

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose}>
        <Pressable style={styles.sheet}>
          <View style={styles.handle} />
          <Text style={styles.name}>{agent.name}</Text>
          <Text style={styles.meta}>{roleLabel} · {agent.office}</Text>

          <View style={styles.actions}>
            {agent.phone ? (
              <>
                <TouchableOpacity
                  style={styles.actionBtn}
                  onPress={() => Linking.openURL(`tel:${agent.phone}`)}
                >
                  <Ionicons name="call" size={20} color={COLORS.primary} />
                  <Text style={styles.actionTxt}>CALL</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={styles.actionBtn}
                  onPress={() => Linking.openURL(`sms:${agent.phone}`)}
                >
                  <Ionicons name="chatbubble" size={20} color={COLORS.secondary} />
                  <Text style={styles.actionTxt}>TEXT</Text>
                </TouchableOpacity>
              </>
            ) : null}
            {agent.email ? (
              <TouchableOpacity
                style={styles.actionBtn}
                onPress={() => Linking.openURL(`mailto:${agent.email}`)}
              >
                <Ionicons name="mail" size={20} color={COLORS.gold} />
                <Text style={styles.actionTxt}>EMAIL</Text>
              </TouchableOpacity>
            ) : null}
          </View>

          <TouchableOpacity style={styles.closeBtn} onPress={onClose}>
            <Text style={styles.closeTxt}>CLOSE</Text>
          </TouchableOpacity>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.6)',
    justifyContent: 'flex-end',
  },
  sheet: {
    backgroundColor: COLORS.surface,
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    padding: 24,
    paddingBottom: 40,
    borderTopWidth: 1,
    borderLeftWidth: 1,
    borderRightWidth: 1,
    borderColor: COLORS.border,
  },
  handle: {
    width: 40,
    height: 4,
    backgroundColor: COLORS.border,
    borderRadius: 2,
    alignSelf: 'center',
    marginBottom: 20,
  },
  name: {
    color: '#fff',
    fontSize: 20,
    fontWeight: '900',
    letterSpacing: 0.3,
  },
  meta: {
    color: COLORS.textDim,
    fontSize: 12,
    marginTop: 4,
    marginBottom: 20,
    letterSpacing: 0.5,
  },
  actions: {
    flexDirection: 'row',
    gap: 10,
    marginBottom: 20,
  },
  actionBtn: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingVertical: 14,
    borderWidth: 1,
    borderColor: COLORS.border,
    borderRadius: 6,
    backgroundColor: COLORS.surface2,
  },
  actionTxt: {
    color: '#fff',
    fontWeight: '900',
    fontSize: 12,
    letterSpacing: 1,
  },
  closeBtn: {
    paddingVertical: 14,
    borderWidth: 1,
    borderColor: COLORS.border,
    borderRadius: 6,
    alignItems: 'center',
  },
  closeTxt: {
    color: COLORS.textDim,
    fontWeight: '900',
    fontSize: 12,
    letterSpacing: 1.5,
  },
});
