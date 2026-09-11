import Link from 'next/link';
import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';

export default async function LandingPage() {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session_token')?.value;
  const isAuthenticated = Boolean(sessionCookie);

  if (isAuthenticated) {
    // Redirect authenticated users to dashboard
    redirect('/dashboard/overview');
  }

  return (
    <div className='flex min-h-svh flex-col items-center justify-center gap-8 bg-background px-4 py-16'>
      <div className='text-center'>
        <h1 className='text-4xl font-bold tracking-tight sm:text-6xl'>
          Your study team, <span className='text-primary'>one workspace</span>
        </h1>
        <p className='mt-6 text-lg text-muted-foreground max-w-md mx-auto'>
          Teamspace brings your group chat, tasks, wiki notes, files, and deadlines together so
          your team can ship the project on time.
        </p>
      </div>
      <div className='flex flex-col sm:flex-row gap-4'>
        <Link
          href='/auth/sign-in'
          className='inline-flex items-center justify-center rounded-md bg-primary px-6 py-3 text-sm font-semibold text-primary-foreground shadow-sm hover:bg-primary/90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 transition-colors'
        >
          Sign In
        </Link>
        <Link
          href='/auth/sign-up'
          className='inline-flex items-center justify-center rounded-md border border-input bg-background px-6 py-3 text-sm font-semibold hover:bg-accent hover:text-accent-foreground transition-colors'
        >
          Create Account
        </Link>
      </div>
    </div>
  );
}
