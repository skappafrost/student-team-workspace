'use client';

import { AuthForm } from '../AuthForm';
import { signUp } from '@/lib/auth';

export default function SignUpPage() {
  return (
    <div className='flex min-h-svh items-center justify-center p-4'>
      <AuthForm mode='sign-up' onSubmit={async (values) => signUp(values.email, values.password)} />
    </div>
  );
}
