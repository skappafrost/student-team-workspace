import KBar from '@/components/kbar';
import AppSidebar from '@/components/layout/app-sidebar';
import Header from '@/components/layout/header';
import { InfoSidebar } from '@/components/layout/info-sidebar';
import { InfobarProvider } from '@/components/ui/infobar';
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar';
import { getCurrentUser, SessionUser } from '@/lib/auth';
import type { Metadata } from 'next';
import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';

export const metadata: Metadata = {
  title: 'Next Shadcn Dashboard Starter',
  description: 'Basic dashboard with Next.js and Shadcn',
  robots: {
    index: false,
    follow: false
  }
};

function DashboardLayoutContent({
  children,
  user
}: {
  children: React.ReactNode;
  user: SessionUser;
}) {
  return (
    <KBar>
      <SidebarProvider defaultOpen={false}>
        <a
          href='#main-content'
          className='bg-background ring-ring sr-only rounded-md px-3 py-2 text-sm font-medium shadow focus:not-sr-only focus:absolute focus:top-2 focus:start-2 focus:z-50 focus:ring-2'
        >
          Skip to content
        </a>
        <AppSidebar />
        <SidebarInset id='main-content' tabIndex={-1} className='scroll-mt-16'>
          <Header user={user} />
          <InfobarProvider defaultOpen={false}>
            {children}
            <InfoSidebar side='right' />
          </InfobarProvider>
        </SidebarInset>
      </SidebarProvider>
    </KBar>
  );
}

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  // Server-side guard: the access token lives in an httpOnly cookie; if the
  // backend cannot resolve the current user, bounce to the sign-in page.
  // `redirect()` never returns, so TS narrows `user` to SessionUser below.
  // First-run: users with zero workspaces go through onboarding instead of
  // landing on half-empty pages. Checked before the dev-mode bypass so the
  // flow is testable locally.
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session_token')?.value;
  let needsOnboarding = false;
  if (sessionCookie) {
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'}/workspaces`,
        { headers: { Cookie: `session_token=${sessionCookie}` }, cache: 'no-store' }
      );
      if (res.ok) {
        const workspaces = (await res.json()) as unknown[];
        needsOnboarding = Array.isArray(workspaces) && workspaces.length === 0;
      }
    } catch {
      // Backend unreachable (e.g. offline dev) — let the pages render their
      // own empty states instead of forcing onboarding.
    }
  }
  // NOTE: redirect() throws — it must stay outside the try/catch above.
  if (needsOnboarding) {
    redirect('/onboarding');
  }

  const user = await getCurrentUser();
  if (!user) {
    if (process.env.NODE_ENV === 'development') {
      const devUser: SessionUser = {
        id: 'dev_1',
        name: 'Dev User',
        email: 'dev@example.com',
        role: 'admin'
      };
      return <DashboardLayoutContent user={devUser}>{children}</DashboardLayoutContent>;
    }
    redirect('/auth/sign-in');
  }

  // Persisting the sidebar state in the cookie.
  void cookieStore.get('sidebar_state')?.value;
  return <DashboardLayoutContent user={user}>{children}</DashboardLayoutContent>;
}
