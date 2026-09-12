'use client';

/**
 * Minimal EN/VI i18n (F12) — dictionary lookup with React context.
 * Keys are the English source strings; missing keys fall back to the key.
 */

import * as React from 'react';

export type Locale = 'en' | 'vi';

const vi: Record<string, string> = {
  // Sidebar groups
  Overview: 'Tổng quan',
  Projects: 'Dự án',
  Deadlines: 'Hạn chót',
  Calendar: 'Lịch',
  Chat: 'Trò chuyện',
  Knowledge: 'Tri thức',
  Wiki: 'Wiki',
  Files: 'Tệp',
  Settings: 'Cài đặt',
  // Sidebar footer / user menu
  'Log out': 'Đăng xuất',
  'Sign out everywhere': 'Đăng xuất mọi nơi',
  'Toggle theme': 'Đổi giao diện',
  Language: 'Ngôn ngữ',
  // Common
  Search: 'Tìm kiếm',
  'AI Search': 'Tìm kiếm AI',
  Dashboard: 'Bảng điều khiển'
};

interface I18nContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: string) => string;
}

const I18nContext = React.createContext<I18nContextValue>({
  locale: 'en',
  setLocale: () => {},
  t: (key) => key
});

const STORAGE_KEY = 'locale';

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = React.useState<Locale>('en');

  React.useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === 'vi' || stored === 'en') setLocaleState(stored);
  }, []);

  const setLocale = React.useCallback((next: Locale) => {
    setLocaleState(next);
    window.localStorage.setItem(STORAGE_KEY, next);
  }, []);

  const t = React.useCallback(
    (key: string) => (locale === 'vi' ? (vi[key] ?? key) : key),
    [locale]
  );

  const value = React.useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  return React.useContext(I18nContext);
}
