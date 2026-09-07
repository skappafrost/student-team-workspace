'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { Icons } from '@/components/icons';
import { useAppForm } from '@/lib/form';
import { z } from 'zod';
import { CreateProjectPayload, ProjectStatus } from '../types';

interface FormValues {
  name: string;
  description?: string;
  status: ProjectStatus;
}

const createProjectSchema = z.object({
  name: z.string().min(1, 'Project name is required').max(100, 'Too long'),
  description: z.string().max(500, 'Too long'),
  status: z.enum(['active', 'archived', 'completed'])
});

interface CreateProjectDialogProps {
  onSubmit: (payload: CreateProjectPayload) => Promise<unknown>;
  isSubmitting?: boolean;
}

export function CreateProjectDialog({ onSubmit, isSubmitting }: CreateProjectDialogProps) {
  const [open, setOpen] = useState(false);
  const form = useAppForm({
    defaultValues: {
      name: '',
      description: '',
      status: 'active' as ProjectStatus
    } as FormValues,
    validators: {
      onSubmit: createProjectSchema
    },
    onSubmit: async ({ value }) => {
      await onSubmit(value);
      setOpen(false);
      form.reset();
    }
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button className='gap-2'>
            <Icons.add className='size-4' />
            New project
          </Button>
        }
      />
      <DialogContent className='sm:max-w-md'>
        <DialogHeader>
          <DialogTitle>Create project</DialogTitle>
          <DialogDescription>Add a new project to the current workspace.</DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            e.stopPropagation();
            void form.handleSubmit();
          }}
          className='space-y-4'
        >
          <form.AppField name='name'>
            {(field) => <field.TextField label='Name' placeholder='e.g. Moonshot' required />}
          </form.AppField>
          <form.AppField name='description'>
            {(field) => (
              <field.TextareaField label='Description' placeholder='What is this project about?' />
            )}
          </form.AppField>
          <form.AppField name='status'>
            {(field) => (
              <field.SelectField
                label='Status'
                options={[
                  { label: 'Active', value: 'active' },
                  { label: 'Archived', value: 'archived' },
                  { label: 'Completed', value: 'completed' }
                ]}
              />
            )}
          </form.AppField>
          <div className='flex justify-end gap-2'>
            <Button type='button' variant='outline' onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type='submit' disabled={isSubmitting}>
              {isSubmitting ? 'Creating…' : 'Create'}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
