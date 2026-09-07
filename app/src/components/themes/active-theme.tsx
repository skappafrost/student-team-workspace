'use client';

import { ReactNode, createContext, useContext, useEffect, useState } from 'react';

import { useTheme } from 'next-themes';

import { DEFAULT_THEME } from './theme.config';

const COOKIE_NAME = 'active_theme';
// Mirrors next-themes' localStorage key so the server can apply the
// persisted dark/light mode to <html> on first paint.
const MODE_COOKIE_NAME = 'theme';

function setCookie(name: string, value: string) {
  if (typeof window === 'undefined') return;

  document.cookie = `${name}=${value}; path=/; max-age=31536000; SameSite=Lax; ${window.location.protocol === 'https:' ? 'Secure;' : ''}`;
}

function setThemeCookie(theme: string) {
  setCookie(COOKIE_NAME, theme);
}

type ThemeContextType = {
  activeTheme: string;
  setActiveTheme: (theme: string) => void;
};

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

export function ActiveThemeProvider({
  children,
  initialTheme
}: {
  children: ReactNode;
  initialTheme?: string;
}) {
  const themeToUse = initialTheme || DEFAULT_THEME;
  const [activeTheme, setActiveTheme] = useState<string>(themeToUse);
  const { resolvedTheme } = useTheme();

  // Persist the dark/light mode as a cookie so the server can render the
  // correct mode on reload/first paint without a flash.
  useEffect(() => {
    if (!resolvedTheme) return;
    setCookie(MODE_COOKIE_NAME, resolvedTheme);
  }, [resolvedTheme]);

  useEffect(() => {
    // Only update if theme has changed
    const currentTheme = document.documentElement.getAttribute('data-theme');
    if (currentTheme !== activeTheme) {
      setThemeCookie(activeTheme);

      // Remove existing data-theme attribute
      document.documentElement.removeAttribute('data-theme');

      // Remove any theme classes from body (cleanup)
      Array.from(document.body.classList)
        .filter((className) => className.startsWith('theme-'))
        .forEach((className) => {
          document.body.classList.remove(className);
        });

      // Set data-theme on html element
      if (activeTheme) {
        document.documentElement.setAttribute('data-theme', activeTheme);
      }
    } else {
      // Still update cookie in case it's missing
      setThemeCookie(activeTheme);
    }
  }, [activeTheme]);

  return (
    <ThemeContext.Provider value={{ activeTheme, setActiveTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useThemeConfig() {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error('useThemeConfig must be used within an ActiveThemeProvider');
  }
  return context;
}
