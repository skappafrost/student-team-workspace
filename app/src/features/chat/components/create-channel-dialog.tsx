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
import { CreateChannelPayload, ChannelType } from '../api/types';

interface FormValues {
  name: string;
  type: ChannelType;
}

const createChannelSchema = z.object({
  name: z.string().min(1, 'Channel name is required').max(100, 'Too long'),
  type: z.enum(['general', 'project', 'private'])
});

interface CreateChannelDialogProps {
  onSubmit: (payload: CreateChannelPayload) => Promise<unknown>;
  isSubmitting?: boolean;
}

export function CreateChannelDialog({ onSubmit, isSubmitting }: CreateChannelDialogProps) {
  const [open, setOpen] = useState(false);
  const form = useAppForm({
    defaultValues: {
      name: '',
      type: 'general'
    } as FormValues,
    validators: {
      onSubmit: createChannelSchema
    },
    onSubmit: async ({ value }) => {
      await onSubmit(value);
      setOpen(false);
      form.reset();
    }
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button className='gap-2' />}>
        <Icons.add className='size-4' />
        New channel
      </DialogTrigger>
      <DialogContent className='sm:max-w-md'>
        <DialogHeader>
          <DialogTitle>Create channel</DialogTitle>
          <DialogDescription>Add a new channel to the current workspace.</DialogDescription>
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
            {(field) => <field.TextField label='Name' placeholder='e.g. general' required />}
          </form.AppField>
          <form.AppField name='type'>
            {(field) => (
              <field.SelectField
                label='Type'
                options={[
                  { label: 'General', value: 'general' },
                  { label: 'Project', value: 'project' },
                  { label: 'Private', value: 'private' }
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
