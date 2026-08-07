// Cross-platform dialogs.
//
// react-native-web ships Alert as `class Alert { static alert() {} }` — an
// empty function. Every Alert.alert call is silently a no-op in the browser,
// so a confirmation dialog never appears and its onPress handler never fires:
// the button looks dead and the action never runs. Error alerts vanish the
// same way, which makes a failed request look like nothing happened at all.
//
// Use confirmAsync/notify instead of Alert.alert so the web build behaves.
import { Alert, Platform } from 'react-native';

interface ConfirmOptions {
  title: string;
  message?: string;
  confirmText?: string;
  cancelText?: string;
  destructive?: boolean;
}

/** Ask the user to confirm. Resolves true if they accept, false otherwise. */
export function confirmAsync({
  title,
  message,
  confirmText = 'OK',
  cancelText = 'Cancel',
  destructive = false,
}: ConfirmOptions): Promise<boolean> {
  if (Platform.OS === 'web') {
    // window.confirm is synchronous and always available in a browser; guard
    // anyway so a non-DOM web runtime (SSR/prerender) cannot throw.
    if (typeof window === 'undefined' || typeof window.confirm !== 'function') {
      return Promise.resolve(false);
    }
    return Promise.resolve(window.confirm(message ? `${title}\n\n${message}` : title));
  }
  return new Promise<boolean>((resolve) => {
    Alert.alert(title, message, [
      { text: cancelText, style: 'cancel', onPress: () => resolve(false) },
      {
        text: confirmText,
        style: destructive ? 'destructive' : 'default',
        onPress: () => resolve(true),
      },
    ], { cancelable: true, onDismiss: () => resolve(false) });
  });
}

/** Show an informational or error message. */
export function notify(title: string, message?: string): void {
  if (Platform.OS === 'web') {
    if (typeof window !== 'undefined' && typeof window.alert === 'function') {
      window.alert(message ? `${title}\n\n${message}` : title);
    }
    return;
  }
  Alert.alert(title, message);
}
