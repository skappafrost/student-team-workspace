'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { LoadingButton } from '@/components/ui/loading-button';
import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';

// Source: shadcn/ui Card + form pattern; step indicator follows the shadcn
// breadcrumb/progress idiom (https://ui.shadcn.com/docs/components).

const STEPS = ['Workspace', 'Invite teammates', 'First project', 'Welcome page'] as const;

const SAMPLE_PAGE_CONTENT = `# Welcome to your workspace 🎉

This is your team's knowledge base. Use it for meeting notes, specs, and decisions.

## Quick start
- Create pages from the **Wiki** section
- Nest pages to build a tree
- Search everything with **Ctrl+K**

Happy collaborating!`;

function slugify(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '');
}

export function OnboardingWizard() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const [wsName, setWsName] = useState('');
  const [emails, setEmails] = useState('');
  const [projectName, setProjectName] = useState('');

  const createWorkspace = async () => {
    const name = wsName.trim();
    if (!name) {
      setError('Workspace name is required');
      return;
    }
    setPending(true);
    setError(null);
    try {
      const res = await fetch('/api/workspace', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ name, slug: slugify(name) || 'workspace' })
      });
      if (!res.ok) {
        const data = (await res.json().catch(() => ({}))) as { error?: string };
        throw new Error(data.error || `Failed to create workspace (${res.status})`);
      }
      setStep(1);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create workspace');
    } finally {
      setPending(false);
    }
  };

  const sendInvites = async () => {
    const list = emails
      .split(/[\n,;]+/)
      .map((e) => e.trim())
      .filter(Boolean);
    setPending(true);
    setError(null);
    try {
      for (const email of list) {
        const res = await fetch('/api/workspace/invites', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ email, role: 'member' })
        });
        if (!res.ok) {
          const data = (await res.json().catch(() => ({}))) as { error?: string };
          throw new Error(data.error || `Invite failed for ${email}`);
        }
      }
      setStep(2);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send invites');
    } finally {
      setPending(false);
    }
  };

  const createProject = async () => {
    const name = projectName.trim();
    if (!name) {
      setError('Project name is required');
      return;
    }
    setPending(true);
    setError(null);
    try {
      const res = await fetch('/api/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ name, description: 'Created during onboarding' })
      });
      if (!res.ok) {
        const data = (await res.json().catch(() => ({}))) as { error?: string };
        throw new Error(data.error || 'Failed to create project');
      }
      setStep(3);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create project');
    } finally {
      setPending(false);
    }
  };

  const createWelcomePage = async () => {
    setPending(true);
    setError(null);
    try {
      const res = await fetch('/api/pages', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          title: 'Welcome',
          slug: 'welcome',
          content: SAMPLE_PAGE_CONTENT
        })
      });
      if (!res.ok) {
        const data = (await res.json().catch(() => ({}))) as { error?: string };
        throw new Error(data.error || 'Failed to create welcome page');
      }
      router.push('/dashboard/overview');
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create welcome page');
      setPending(false);
    }
  };

  return (
    <Card className='w-full max-w-lg'>
      <CardHeader>
        <div className='mb-2 flex items-center gap-2' aria-label='Progress'>
          {STEPS.map((label, i) => (
            <div key={label} className='flex items-center gap-2'>
              <span
                className={cn(
                  'flex h-6 w-6 items-center justify-center rounded-full text-xs font-medium',
                  i < step && 'bg-primary text-primary-foreground',
                  i === step && 'border-2 border-primary text-primary',
                  i > step && 'bg-muted text-muted-foreground'
                )}
                aria-current={i === step ? 'step' : undefined}
              >
                {i < step ? <Icons.check className='h-3.5 w-3.5' /> : i + 1}
              </span>
              {i < STEPS.length - 1 && <span className='h-px w-6 bg-border' aria-hidden />}
            </div>
          ))}
        </div>
        <CardTitle>{STEPS[step]}</CardTitle>
        <CardDescription>
          {step === 0 && 'Name your team workspace. You can rename it later.'}
          {step === 1 && 'Invite teammates by email. You can also do this later.'}
          {step === 2 && 'Create your first project to hold kanban tasks.'}
          {step === 3 && 'We will add a sample wiki page so your knowledge base is not empty.'}
        </CardDescription>
      </CardHeader>
      <CardContent className='flex flex-col gap-4'>
        {step === 0 && (
          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='ws-name'>Workspace name</Label>
            <Input
              id='ws-name'
              value={wsName}
              onChange={(e) => setWsName(e.currentTarget.value)}
              placeholder='e.g. CS101 Group Project'
              autoFocus
            />
          </div>
        )}
        {step === 1 && (
          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='invite-emails'>Teammate emails (one per line)</Label>
            <textarea
              id='invite-emails'
              className='border-input bg-background ring-offset-background placeholder:text-muted-foreground focus-visible:ring-ring min-h-24 w-full rounded-md border px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none'
              value={emails}
              onChange={(e) => setEmails(e.currentTarget.value)}
              placeholder={'minh@example.com\nlan@example.com'}
            />
          </div>
        )}
        {step === 2 && (
          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='project-name'>Project name</Label>
            <Input
              id='project-name'
              value={projectName}
              onChange={(e) => setProjectName(e.currentTarget.value)}
              placeholder='e.g. Midterm report'
              autoFocus
            />
          </div>
        )}
        {step === 3 && (
          <p className='text-sm text-muted-foreground'>
            Click finish to create the welcome page and jump into your dashboard.
          </p>
        )}
        {error && (
          <p role='alert' className='text-sm text-destructive'>
            {error}
          </p>
        )}
      </CardContent>
      <CardFooter className='flex justify-between'>
        {step === 1 || step === 2 ? (
          <Button variant='ghost' onClick={() => setStep(step + 1)} disabled={pending}>
            Skip
          </Button>
        ) : (
          <span />
        )}
        {step === 0 && (
          <LoadingButton onClick={createWorkspace} loading={pending}>
            Create workspace
          </LoadingButton>
        )}
        {step === 1 && (
          <LoadingButton onClick={sendInvites} loading={pending}>
            Send invites
          </LoadingButton>
        )}
        {step === 2 && (
          <LoadingButton onClick={createProject} loading={pending}>
            Create project
          </LoadingButton>
        )}
        {step === 3 && (
          <LoadingButton onClick={createWelcomePage} loading={pending}>
            Finish
          </LoadingButton>
        )}
      </CardFooter>
    </Card>
  );
}
