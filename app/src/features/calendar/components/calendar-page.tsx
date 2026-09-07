'use client';

import { useCallback, useEffect, useState } from 'react';
import PageContainer from '@/components/layout/page-container';
import { startOfMonth, endOfMonth } from 'date-fns';
import { toast } from 'sonner';
import { CalendarView } from './calendar-view';
import { CreateEventDialog } from './create-event-dialog';
import { CalendarEvent, CreateEventPayload } from '../api/types';
import { createEvent, getEvents } from '../api/service';

export default function CalendarPage() {
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [currentMonth, setCurrentMonth] = useState(new Date());

  const refresh = useCallback(async () => {
    setIsLoading(true);
    try {
      const start = startOfMonth(currentMonth).toISOString();
      const end = endOfMonth(currentMonth).toISOString();
      const data = await getEvents({ start, end });
      setEvents(data);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to load events');
    } finally {
      setIsLoading(false);
    }
  }, [currentMonth]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleCreate = async (payload: CreateEventPayload) => {
    setIsSubmitting(true);
    try {
      const event = await createEvent(payload);
      setEvents((prev) => [...prev, event]);
      toast.success('Event created');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to create event');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <PageContainer
      pageTitle='Calendar'
      pageDescription='Manage your workspace events.'
      pageHeaderAction={
        <CreateEventDialog onSubmit={handleCreate} isSubmitting={isSubmitting}>
          <button
            type='button'
            className='inline-flex h-9 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground shadow hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50'
          >
            New event
          </button>
        </CreateEventDialog>
      }
    >
      <CalendarView
        events={events}
        currentMonth={currentMonth}
        onMonthChange={setCurrentMonth}
        onCreateEvent={handleCreate}
        isLoading={isLoading || isSubmitting}
      />
    </PageContainer>
  );
}
