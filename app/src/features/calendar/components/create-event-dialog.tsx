'use client';

import { useState } from 'react';
import { z } from 'zod';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { useAppForm } from '@/lib/form';
import { Icons } from '@/components/icons';
import { CalendarEventType, Recurrence } from '../api/types';

interface FormValues {
  title: string;
  description: string;
  start_at: string;
  end_at?: string;
  all_day: boolean;
  event_type: CalendarEventType;
  recurrence: Recurrence;
}

const eventTypeOptions: { value: CalendarEventType; label: string }[] = [
  { value: 'meeting', label: 'Meeting' },
  { value: 'deadline', label: 'Deadline' },
  { value: 'exam', label: 'Exam' },
  { value: 'reminder', label: 'Reminder' }
];

const recurrenceOptions: { value: Recurrence; label: string }[] = [
  { value: 'none', label: 'Does not repeat' },
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' }
];

const createEventSchema = z.object({
  title: z.string().min(1, 'Title is required').max(100, 'Too long'),
  description: z.string().max(500, 'Too long'),
  start_at: z.string().min(1, 'Start date is required'),
  end_at: z.string().max(500).optional(),
  all_day: z.boolean(),
  event_type: z.enum(['deadline', 'exam', 'meeting', 'reminder']),
  recurrence: z.enum(['none', 'daily', 'weekly', 'monthly'])
});

interface CreateEventDialogProps {
  onSubmit: (payload: {
    title: string;
    description?: string;
    start_at: string;
    end_at?: string;
    all_day?: boolean;
    event_type?: CalendarEventType;
    recurrence?: Recurrence;
  }) => Promise<void>;
  isSubmitting?: boolean;
  children?: React.ReactNode;
}

export function CreateEventDialog({ onSubmit, isSubmitting, children }: CreateEventDialogProps) {
  const [open, setOpen] = useState(false);
  const form = useAppForm({
    defaultValues: {
      title: '',
      description: '',
      start_at: '',
      end_at: undefined,
      all_day: false,
      event_type: 'meeting' as CalendarEventType,
      recurrence: 'none' as Recurrence
    } as FormValues,
    validators: {
      onSubmit: createEventSchema
    },
    onSubmit: async ({ value }) => {
      await onSubmit({
        title: value.title,
        description: value.description || undefined,
        start_at: value.start_at,
        end_at: value.end_at || undefined,
        all_day: value.all_day,
        event_type: value.event_type,
        recurrence: value.recurrence
      });
      setOpen(false);
      form.reset();
    }
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      {children ? (
        <DialogTrigger render={children as React.ReactElement} />
      ) : (
        <DialogTrigger
          render={
            <Button className='gap-2'>
              <Icons.add className='size-4' />
              New event
            </Button>
          }
        />
      )}
      <DialogContent className='sm:max-w-md'>
        <DialogHeader>
          <DialogTitle>Create event</DialogTitle>
          <DialogDescription>Add a new event to the calendar.</DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            e.stopPropagation();
            void form.handleSubmit();
          }}
          className='space-y-4'
        >
          <form.AppField name='title'>
            {(field) => (
              <field.TextField label='Title' placeholder='e.g. Sprint planning' required />
            )}
          </form.AppField>
          <form.AppField name='description'>
            {(field) => (
              <field.TextareaField label='Description' placeholder='Add details (optional)' />
            )}
          </form.AppField>
          <div className='grid grid-cols-2 gap-4'>
            <form.AppField name='start_at'>
              {(field) => (
                <field.TextField
                  label='Start'
                  type='datetime-local'
                  placeholder='yyyy-mm-dd --:--'
                  required
                />
              )}
            </form.AppField>
            <form.AppField name='end_at'>
              {(field) => (
                <field.TextField label='End' type='datetime-local' placeholder='yyyy-mm-dd --:--' />
              )}
            </form.AppField>
          </div>
          <form.AppField name='event_type'>
            {(field) => <field.SelectField label='Event type' options={eventTypeOptions} />}
          </form.AppField>
          <form.AppField name='recurrence'>
            {(field) => <field.SelectField label='Repeats' options={recurrenceOptions} />}
          </form.AppField>
          <form.AppField name='all_day'>
            {(field) => <field.SwitchField label='All day' />}
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
