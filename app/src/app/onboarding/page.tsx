import { getCurrentUser } from '@/lib/auth';
import { redirect } from 'next/navigation';
import { OnboardingWizard } from '@/features/workspace/components/onboarding-wizard';

export const metadata = {
  title: 'Welcome — set up your workspace'
};

export default async function OnboardingPage() {
  const user = await getCurrentUser();
  if (!user) {
    redirect('/auth/sign-in');
  }

  return (
    <main className='flex min-h-svh items-center justify-center bg-background p-4'>
      <OnboardingWizard />
    </main>
  );
}
