// Shared inline search field for list screens (Team, Shoutouts, Nominations).
import React from 'react';
import { View, TextInput, TouchableOpacity, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS } from '../lib/auth';

interface SearchBarProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  testID?: string;
}

export function SearchBar({ value, onChange, placeholder, testID }: SearchBarProps) {
  return (
    <View style={styles.wrap}>
      <Ionicons name="search" size={14} color={COLORS.textDim} />
      <TextInput
        style={styles.input}
        value={value}
        onChangeText={onChange}
        placeholder={placeholder ?? 'Search'}
        placeholderTextColor={COLORS.textMuted}
        autoCapitalize="none"
        autoCorrect={false}
        returnKeyType="search"
        testID={testID}
      />
      {value.length > 0 ? (
        <TouchableOpacity onPress={() => onChange('')} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }} testID={testID ? `${testID}-clear` : undefined}>
          <Ionicons name="close-circle" size={16} color={COLORS.textDim} />
        </TouchableOpacity>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flexDirection: 'row', alignItems: 'center', gap: 8,
    marginHorizontal: 16, marginBottom: 8, paddingHorizontal: 10,
    borderWidth: 1, borderColor: COLORS.border, borderRadius: 6,
    backgroundColor: COLORS.surface,
  },
  input: { flex: 1, color: '#fff', fontSize: 13, paddingVertical: 8 },
});
