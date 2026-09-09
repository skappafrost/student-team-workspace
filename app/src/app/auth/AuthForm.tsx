'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import * as z from 'zod';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { FieldGroup } from '@/components/ui/field';
import { Icons } from '@/components/icons';
import { type SessionUser } from '@/lib/auth';
import { useAppForm } from '@/lib/form';

const baseSchema = z.object({
  email: z.email('Please enter a valid email address.'),
  password: z
    .string()
    .min(8, 'Password must be at least 8 characters.')
    .max(128, 'Password must be at most 128 characters.')
});

const schemas = {
  'sign-in': baseSchema,
  'sign-up': baseSchema.extend({
    confirmPassword: z.string().min(1, 'Please confirm your password.')
  })
};

type Mode = keyof typeof schemas;

const COPY: Record<
  Mode,
  {
    title: string;
    description: string;
    submit: string;
    switchTo: string;
    switchPrompt: string;
  }
> = {
  'sign-in': {
    title: 'Welcome back',
    description: 'Enter your email below to sign in to your account',
    submit: 'Sign in',
    switchPrompt: "Don't have an account?",
    switchTo: 'Sign up'
  },
  'sign-up': {
    title: 'Create an account',
    description: 'Enter your email below to create your account',
    submit: 'Sign up',
    switchPrompt: 'Already have an account?',
    switchTo: 'Sign in'
  }
};

/**
 * Origin UI-style auth block (D5): single centered card, email + password
 * (+ confirm on sign-up), inline field errors, inline API error.
 * Auth contract lives in lib/auth.ts — this component only renders and routes.
 * `onSubmit` is injected by the page so wiring stays swappable.
 */
export function AuthForm({
  mode,
  onSubmit
}: {
  mode: Mode;
  onSubmit: (values: {
    email: string;
    password: string;
    confirmPassword?: string;
  }) => Promise<SessionUser>;
}) {
  const [apiError, setApiError] = React.useState<string | null>(null);
  const router = useRouter();
  const copy = COPY[mode];
  const schema = schemas[mode];

  const form = useAppForm({
    defaultValues:
      mode === 'sign-up'
        ? { email: '', password: '', confirmPassword: '' }
        : { email: '', password: '' },
    validators: { onSubmit: schema },
    onSubmit: async ({ value }) => {
      setApiError(null);
      try {
        await onSubmit(value);
        router.push('/dashboard');
        router.refresh();
      } catch (err) {
        setApiError(err instanceof Error ? err.message : 'Something went wrong. Please try again.');
      }
    }
  });

  return (
    <Card className='w-full max-w-sm'>
      <CardHeader>
        <div className='flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground'>
          <Icons.dashboard className='size-5' />
        </div>
        <CardTitle className='text-2xl'>{copy.title}</CardTitle>
        <CardDescription>{copy.description}</CardDescription>
      </CardHeader>
      <CardContent>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            e.stopPropagation();
            void form.handleSubmit();
          }}
        >
          <FieldGroup className='gap-4'>
            <form.AppForm>
              {apiError && (
                <Alert variant='destructive' role='alert'>
                  <Icons.warning className='size-4' />
                  <AlertDescription>{apiError}</AlertDescription>
                </Alert>
              )}
            </form.AppForm>
            <form.AppField
              name='email'
              children={(field) => (
                <field.TextField
                  label='Email'
                  required
                  type='email'
                  placeholder='m@example.com'
                  autoComplete='email'
                />
              )}
            />
            <form.AppField
              name='password'
              children={(field) => (
                <field.TextField
                  label='Password'
                  required
                  type='password'
                  autoComplete={mode === 'sign-in' ? 'current-password' : 'new-password'}
                />
              )}
            />
            {mode === 'sign-up' && (
              <form.AppField
                name='confirmPassword'
                validators={{
                  onChangeListenTo: ['password'],
                  onChange: ({ value, fieldApi }) =>
                    value !== fieldApi.form.getFieldValue('password')
                      ? { message: 'Passwords do not match.' }
                      : undefined
                }}
                children={(field) => (
                  <field.TextField
                    label='Confirm Password'
                    required
                    type='password'
                    autoComplete='new-password'
                  />
                )}
              />
            )}
            <form.AppForm>
              <form.SubmitButton className='w-full'>{copy.submit}</form.SubmitButton>
            </form.AppForm>
            <Link
              href={mode === 'sign-in' ? '/auth/sign-up' : '/auth/sign-in'}
              className={buttonVariants({
                variant: 'outline',
                className: 'w-full'
              })}
            >
              Continue with {mode === 'sign-in' ? 'sign up' : 'sign in'}
            </Link>
          </FieldGroup>
        </form>
        <div className='mt-4 text-center text-sm'>
          {copy.switchPrompt}{' '}
          <Link
            href={mode === 'sign-in' ? '/auth/sign-up' : '/auth/sign-in'}
            className='underline underline-offset-4'
          >
            {copy.switchTo}
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}

export type { SessionUser };
