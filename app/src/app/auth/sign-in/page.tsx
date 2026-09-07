'use client';

import { AuthForm } from '../AuthForm';
import { signIn } from '@/lib/auth';

export default function SignInPage() {
  return (
    <div className='flex min-h-svh items-center justify-center p-4'>
      <AuthForm mode='sign-in' onSubmit={(values) => signIn(values.email, values.password)} />
    </div>
  );
}
