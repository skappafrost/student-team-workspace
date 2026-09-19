import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { HeroScene } from './hero-scene';

export default async function LandingPage() {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session_token')?.value;

  if (sessionCookie) {
    // Redirect authenticated users to dashboard
    redirect('/dashboard/overview');
  }

  return <HeroScene />;
}
