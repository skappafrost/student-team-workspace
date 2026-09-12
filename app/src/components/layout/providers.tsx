'use client';
import React from 'react';
import { ActiveThemeProvider } from '@/components/themes/active-theme';
import QueryProvider from '@/components/layout/query-provider';
import { I18nProvider } from '@/lib/i18n';

export default function Providers({
  activeThemeValue,
  children
}: {
  activeThemeValue: string;
  children: React.ReactNode;
}) {
  return (
    <>
      <ActiveThemeProvider initialTheme={activeThemeValue}>
        <I18nProvider>
          <QueryProvider>{children}</QueryProvider>
        </I18nProvider>
      </ActiveThemeProvider>
    </>
  );
}
