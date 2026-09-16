// A confirmation that cannot be tapped through by accident: the person has to
// type a word before the action unlocks.
//
// Reserved for the few operations that destroy a record outright. Removing
// someone from the roster archives them and an admin can restore them, so an
// ordinary confirm is right there. Merging duplicate profiles DELETES one of
// them and moves its reports, production and login onto the other — there is
// no restore for it — and that deserves a deliberate pause.
//
// Built as a modal with a TextInput rather than a dialog helper on purpose:
// Alert.prompt is iOS-only, and react-native-web has no prompt at all, so a
// helper-based version would silently do nothing on two of the three targets.
import React, { useState } from 'react';
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity, Modal, ActivityIndicator,
} from 'react-native';
import { COLORS } from '../lib/auth';

interface Props {
  visible: boolean;
  title: string;
  /** What is about to happen, in plain words. */
  message: string;
  /** The exact word the person must type. Compared case-insensitively. */
  word: string;
  confirmText?: string;
  busy?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export function TypedConfirm({
  visible, title, message, word, confirmText = 'Confirm', busy, onCancel, onConfirm,
}: Props) {
  const [typed, setTyped] = useState('');
  const matches = typed.trim().toUpperCase() === word.toUpperCase();

  const close = () => { setTyped(''); onCancel(); };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={close}>
      <View style={styles.backdrop}>
        <View style={styles.card}>
          <Text style={styles.title}>{title}</Text>
          <Text style={styles.message}>{message}</Text>
          <Text style={styles.prompt}>
            Type <Text style={styles.word}>{word}</Text> to continue.
          </Text>
          <TextInput
            style={styles.input}
            value={typed}
            onChangeText={setTyped}
            autoCapitalize="characters"
            autoCorrect={false}
            editable={!busy}
            placeholder={word}
            placeholderTextColor={COLORS.textMuted}
            testID="typed-confirm-input"
          />
          <View style={styles.row}>
            <TouchableOpacity style={styles.cancel} onPress={close} disabled={busy}>
              <Text style={styles.cancelTxt}>CANCEL</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.confirm, (!matches || busy) && styles.confirmOff]}
              disabled={!matches || busy}
              onPress={() => { setTyped(''); onConfirm(); }}
              testID="typed-confirm-go"
            >
              {busy
                ? <ActivityIndicator color="#000" />
                : <Text style={styles.confirmTxt}>{confirmText}</Text>}
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1, backgroundColor: 'rgba(0,0,0,0.7)',
    justifyContent: 'center', padding: 24,
  },
  card: {
    backgroundColor: '#141414', borderRadius: 14, padding: 18,
    borderWidth: 1, borderColor: COLORS.border,
  },
  title: { color: COLORS.red, fontWeight: '900', fontSize: 13, letterSpacing: 1.2 },
  message: { color: COLORS.textDim, fontSize: 13, lineHeight: 19, marginTop: 10 },
  prompt: { color: COLORS.textDim, fontSize: 13, marginTop: 14 },
  word: { color: '#fff', fontWeight: '900', letterSpacing: 1 },
  input: {
    backgroundColor: COLORS.surface2, borderWidth: 1, borderColor: COLORS.border,
    borderRadius: 8, paddingHorizontal: 12, paddingVertical: 10, marginTop: 8,
    color: '#fff', fontSize: 15, fontWeight: '800', letterSpacing: 1,
  },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 16 },
  cancel: { flex: 1, alignItems: 'center', paddingVertical: 12 },
  cancelTxt: { color: COLORS.textDim, fontWeight: '900', fontSize: 12, letterSpacing: 1 },
  confirm: {
    flex: 1, alignItems: 'center', paddingVertical: 12,
    borderRadius: 8, backgroundColor: COLORS.red,
  },
  confirmOff: { opacity: 0.35 },
  confirmTxt: { color: '#000', fontWeight: '900', fontSize: 12, letterSpacing: 1 },
});
