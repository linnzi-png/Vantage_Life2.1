// Add Team Member — any upline (SA and above, level_2+) can onboard a new
// person DIRECTLY UNDER THEMSELVES from the Team tab. The backend forces
// upline = requester and inherits the requester's office, so the new member
// rolls up through the existing chain (SA → GA → MGA → RGA) automatically.
// Arbitrary placement (other office / other upline) stays an Admin-only task.
import React, { useState } from 'react';
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity, ScrollView,
  Modal, KeyboardAvoidingView, Platform, ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { api, COLORS, levelNum, Role } from '../lib/auth';
import { notify } from '../lib/dialog';

interface Props {
  visible: boolean;
  onClose: () => void;
  myRole?: Role | null;    // requester's internal role, e.g. "level_2"
  onAdded: () => void;     // refresh the team list
}

// Roles an upline may hand out: strictly below their own level. The io_role
// is the field-facing title stored alongside the RBAC role.
//
// A trainee is an Agent (level_1) carrying the existing `inTraining` title —
// not a new access tier. That code is already the roster's own: the imported
// MJ roster, the Admin panel's io_role list, and IO_ROLE_TITLES all use it, so
// reusing it keeps every trainee under one title instead of splitting them
// across two names that mean the same thing.
//
// GA and SA are both level_2 — the tier the roster and CLAUDE.md give them
// (level_3 is MGA). GA sat at level_3 here until 2026-09, which handed every
// GA added from this sheet MGA-tier visibility over their whole branch. The
// title never granted the tier; the wrong tier was being sent outright.
const ROLE_OPTIONS: { role: Role; io_role: string; label: string }[] = [
  { role: 'level_1', io_role: 'Agent',      label: 'AGENT' },
  { role: 'level_1', io_role: 'inTraining', label: 'TRAINEE' },
  { role: 'level_2', io_role: 'SA',         label: 'SA' },
  { role: 'level_2', io_role: 'GA',         label: 'GA' },
];

export function AddTeamMemberSheet({ visible, onClose, myRole, onAdded }: Props) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [roleIdx, setRoleIdx] = useState(0);
  const [rookie, setRookie] = useState<boolean | null>(null);
  const [state, setState] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const myLevel = levelNum(myRole);
  // Strictly below the requester's own level (matches the backend rule).
  const allowed = ROLE_OPTIONS.filter((o) => levelNum(o.role) < myLevel);

  const reset = () => {
    setName(''); setEmail(''); setPhone(''); setRoleIdx(0); setRookie(null); setState('');
  };

  const submit = async () => {
    const pick = allowed[roleIdx] || allowed[0];
    if (!name.trim() || !email.trim()) { notify('Missing info', 'Name and email are required.'); return; }
    if (rookie === null) { notify('Missing info', 'Choose Veteran or Rookie.'); return; }
    setSubmitting(true);
    try {
      await api('/api/team/add-person', {
        method: 'POST',
        body: JSON.stringify({
          name: name.trim(), email: email.trim(), phone,
          role: pick.role, io_role: pick.io_role,
          is_rookie: rookie, state: state.trim() || null,
        }),
      });
      notify('Added', `${name.trim()} is now on your team, directly under you.`);
      reset(); onAdded(); onClose();
    } catch (e: unknown) {
      notify('Error', e instanceof Error ? e.message : 'Failed to add team member');
    } finally {
      setSubmitting(false);
    }
  };

  if (!visible) return null;

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <KeyboardAvoidingView style={styles.sheet} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
          <View style={styles.head}>
            <View style={{ flex: 1 }}>
              <Text style={styles.kicker}>ADD TEAM MEMBER</Text>
              <Text style={styles.sub}>They will be placed directly under you</Text>
            </View>
            <TouchableOpacity onPress={onClose} testID="add-member-close" hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
              <Ionicons name="close" size={24} color={COLORS.textDim} />
            </TouchableOpacity>
          </View>

          <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
            <Text style={styles.label}>FULL NAME</Text>
            <TextInput style={styles.input} value={name} onChangeText={setName}
              placeholder="First Last" placeholderTextColor={COLORS.textDim}
              autoCapitalize="words" testID="add-member-name" />

            <Text style={styles.label}>EMAIL (used to link their sign-in)</Text>
            <TextInput style={styles.input} value={email} onChangeText={setEmail}
              placeholder="name@example.com" placeholderTextColor={COLORS.textDim}
              autoCapitalize="none" keyboardType="email-address" testID="add-member-email" />

            <Text style={styles.label}>PHONE</Text>
            <TextInput style={styles.input} value={phone} onChangeText={setPhone}
              placeholder="(555) 555-5555" placeholderTextColor={COLORS.textDim}
              keyboardType="phone-pad" testID="add-member-phone" />

            {allowed.length > 1 ? (
              <>
                <Text style={styles.label}>ROLE</Text>
                <View style={styles.chipRow}>
                  {allowed.map((o, i) => (
                    // Keyed by io_role, not role — Agent and Trainee share level_1.
                    <TouchableOpacity key={o.io_role}
                      style={[styles.chip, roleIdx === i && styles.chipOn]}
                      onPress={() => setRoleIdx(i)} testID={`add-member-role-${o.io_role}`}>
                      <Text style={[styles.chipTxt, roleIdx === i && styles.chipTxtOn]}>{o.label}</Text>
                    </TouchableOpacity>
                  ))}
                </View>
              </>
            ) : null}

            <Text style={styles.label}>TENURE (required)</Text>
            <View style={styles.chipRow}>
              <TouchableOpacity style={[styles.chip, rookie === false && styles.chipOn]}
                onPress={() => setRookie(false)} testID="add-member-vet">
                <Text style={[styles.chipTxt, rookie === false && styles.chipTxtOn]}>VETERAN</Text>
              </TouchableOpacity>
              <TouchableOpacity style={[styles.chip, rookie === true && styles.chipOn]}
                onPress={() => setRookie(true)} testID="add-member-rookie">
                <Text style={[styles.chipTxt, rookie === true && styles.chipTxtOn]}>ROOKIE</Text>
              </TouchableOpacity>
            </View>

            <Text style={styles.label}>RESIDENT STATE (optional, e.g. MI)</Text>
            <TextInput style={[styles.input, { width: 90 }]} value={state}
              onChangeText={(t) => setState(t.toUpperCase().slice(0, 2))}
              placeholder="MI" placeholderTextColor={COLORS.textDim}
              autoCapitalize="characters" testID="add-member-state" />

            <TouchableOpacity
              style={[styles.submit, submitting && { opacity: 0.6 }]}
              onPress={submit} disabled={submitting} testID="add-member-submit">
              {submitting
                ? <ActivityIndicator color="#000" />
                : <Text style={styles.submitTxt}>ADD TO MY TEAM</Text>}
            </TouchableOpacity>
          </ScrollView>
        </KeyboardAvoidingView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop:  { flex: 1, backgroundColor: 'rgba(0,0,0,0.7)', justifyContent: 'flex-end' },
  sheet:     { backgroundColor: COLORS.bg, borderTopLeftRadius: 14, borderTopRightRadius: 14, maxHeight: '88%', borderWidth: 1, borderColor: COLORS.border },
  head:      { flexDirection: 'row', alignItems: 'center', padding: 16, paddingBottom: 8 },
  kicker:    { color: COLORS.primary, fontSize: 12, fontWeight: '900', letterSpacing: 1.6 },
  sub:       { color: COLORS.textDim, fontSize: 11, marginTop: 2 },
  scroll:    { padding: 16, paddingBottom: 40 },
  label:     { color: COLORS.textDim, fontSize: 10, fontWeight: '900', letterSpacing: 1.2, marginTop: 12, marginBottom: 6 },
  input:     { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: 6, color: '#fff', paddingHorizontal: 12, paddingVertical: 10, fontSize: 14 },
  // wrap: an RGA sees four role chips, which can overrun a narrow phone.
  chipRow:   { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip:      { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface },
  chipOn:    { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  chipTxt:   { color: COLORS.textDim, fontSize: 11, fontWeight: '900', letterSpacing: 0.6 },
  chipTxtOn: { color: '#000' },
  submit:    { backgroundColor: COLORS.primary, borderRadius: 8, alignItems: 'center', paddingVertical: 14, marginTop: 20 },
  submitTxt: { color: '#000', fontWeight: '900', fontSize: 13, letterSpacing: 1 },
});
