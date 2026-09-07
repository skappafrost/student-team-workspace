'use client';

import { useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Icons } from '@/components/icons';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription
} from '@/components/ui/sheet';
import { CalendarEvent } from '../api/types';

// react-day-picker is the preferred calendar library per project guidelines.
import { DayPicker, getDefaultClassNames } from 'react-day-picker';
import { format, parseISO, isSameDay } from 'date-fns';
import { cn } from '@/lib/utils';
import { CreateEventDialog } from './create-event-dialog';

interface CalendarViewProps {
  events: CalendarEvent[];
  currentMonth: Date;
  onMonthChange: (date: Date) => void;
  onCreateEvent: (payload: {
    title: string;
    description?: string;
    start_at: string;
    end_at?: string;
    all_day?: boolean;
    event_type?: 'deadline' | 'exam' | 'meeting' | 'reminder';
  }) => Promise<void>;
  isLoading?: boolean;
}

const eventTypeVariant: Record<
  CalendarEvent['event_type'],
  'default' | 'secondary' | 'warning' | 'destructive' | 'outline'
> = {
  deadline: 'warning',
  exam: 'destructive',
  meeting: 'default',
  reminder: 'secondary'
};

export function CalendarView({
  events,
  currentMonth,
  onMonthChange,
  onCreateEvent,
  isLoading
}: CalendarViewProps) {
  const [selectedDate, setSelectedDate] = useState<Date | null>(null);
  const defaultClassNames = getDefaultClassNames();

  const eventsByDate = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>();
    for (const event of events) {
      const date = parseISO(event.start_at);
      const key = format(date, 'yyyy-MM-dd');
      const existing = map.get(key) ?? [];
      existing.push(event);
      map.set(key, existing);
    }
    return map;
  }, [events]);

  const selectedEvents = selectedDate
    ? (eventsByDate.get(format(selectedDate, 'yyyy-MM-dd')) ?? [])
    : [];

  const handleDayClick = (date: Date) => {
    setSelectedDate(date);
  };

  return (
    <>
      <CalendarViewShell
        currentMonth={currentMonth}
        onMonthChange={onMonthChange}
        onCreateEvent={onCreateEvent}
        isLoading={isLoading}
      >
        <DayPicker
          month={currentMonth}
          onMonthChange={onMonthChange}
          showOutsideDays
          className='w-full'
          classNames={{
            root: cn('w-full', defaultClassNames.root),
            months: cn('w-full', defaultClassNames.months),
            month: cn('w-full', defaultClassNames.month),
            nav: cn('flex items-center justify-between', defaultClassNames.nav),
            button_previous: cn('size-8', defaultClassNames.button_previous),
            button_next: cn('size-8', defaultClassNames.button_next),
            month_caption: cn('text-sm font-medium', defaultClassNames.month_caption),
            caption_label: cn('text-sm font-medium', defaultClassNames.caption_label),
            month_grid: cn('w-full border-collapse', defaultClassNames.month_grid),
            weekdays: cn('flex', defaultClassNames.weekdays),
            weekday: cn(
              'flex-1 text-center text-xs font-normal text-muted-foreground',
              defaultClassNames.weekday
            ),
            week: cn('flex w-full', defaultClassNames.week),
            day: cn(
              'relative flex h-full min-h-[88px] flex-col items-start justify-start border-b border-r p-1 text-left transition-colors hover:bg-muted/50',
              defaultClassNames.day
            ),
            outside: cn('text-muted-foreground opacity-50', defaultClassNames.outside),
            disabled: cn('text-muted-foreground opacity-50', defaultClassNames.disabled),
            hidden: cn('invisible', defaultClassNames.hidden)
          }}
          components={{
            DayButton: ({ day, ...props }) => {
              const date = day.date;
              const key = format(date, 'yyyy-MM-dd');
              const dayEvents = eventsByDate.get(key) ?? [];
              const today = isSameDay(date, new Date());
              return (
                <button
                  {...props}
                  type='button'
                  onClick={() => handleDayClick(date)}
                  className={cn(
                    'relative flex h-full w-full flex-col items-start justify-start rounded-md p-1 transition-colors',
                    today && 'bg-muted font-medium',
                    'hover:bg-muted/70'
                  )}
                >
                  <span className={cn('text-xs', today && 'text-primary font-semibold')}>
                    {format(date, 'd')}
                  </span>
                  <div className='mt-1 flex w-full flex-col gap-0.5 overflow-hidden'>
                    {dayEvents.slice(0, 3).map((event) => (
                      <EventChip key={event.id} event={event} />
                    ))}
                    {dayEvents.length > 3 && (
                      <span className='text-[10px] text-muted-foreground'>
                        +{dayEvents.length - 3} more
                      </span>
                    )}
                  </div>
                </button>
              );
            }
          }}
        />
      </CalendarViewShell>

      <Sheet open={!!selectedDate} onOpenChange={() => setSelectedDate(null)}>
        <SheetContent side='right' className='sm:max-w-md'>
          <SheetHeader>
            <SheetTitle>
              {selectedDate ? format(selectedDate, 'EEEE, MMMM do') : 'Day details'}
            </SheetTitle>
            <SheetDescription>
              {selectedEvents.length === 0
                ? 'No events for this day.'
                : `${selectedEvents.length} event${selectedEvents.length === 1 ? '' : 's'}`}
            </SheetDescription>
          </SheetHeader>
          <div className='mt-4 flex flex-col gap-3'>
            {selectedEvents.map((event) => (
              <EventCard key={event.id} event={event} />
            ))}
            {selectedEvents.length === 0 && (
              <div className='text-muted-foreground text-sm'>
                Click &quot;New event&quot; to add one.
              </div>
            )}
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}

function CalendarViewShell({
  children,
  currentMonth,
  onMonthChange,
  onCreateEvent,
  isLoading
}: {
  children: React.ReactNode;
  currentMonth: Date;
  onMonthChange: (date: Date) => void;
  onCreateEvent: (payload: {
    title: string;
    description?: string;
    start_at: string;
    end_at?: string;
    all_day?: boolean;
    event_type?: 'deadline' | 'exam' | 'meeting' | 'reminder';
  }) => Promise<void>;
  isLoading?: boolean;
}) {
  return (
    <div className='flex flex-col gap-4'>
      <div className='flex items-center justify-between'>
        <div className='flex items-center gap-2'>
          <Icons.calendar className='size-4 text-muted-foreground' />
          <span className='text-sm text-muted-foreground'>{format(currentMonth, 'MMMM yyyy')}</span>
        </div>
        <div className='flex items-center gap-2'>
          <Button variant='outline' size='sm' onClick={() => onMonthChange(new Date())}>
            Today
          </Button>
          <CreateEventDialog onSubmit={onCreateEvent} isSubmitting={isLoading}>
            <Button size='sm' className='gap-1'>
              <Icons.add className='size-4' />
              New event
            </Button>
          </CreateEventDialog>
        </div>
      </div>
      {children}
    </div>
  );
}

function EventChip({ event }: { event: CalendarEvent }) {
  return (
    <Badge variant={eventTypeVariant[event.event_type]} className='w-full justify-start truncate'>
      <span className='truncate'>{event.title}</span>
    </Badge>
  );
}

function EventCard({ event }: { event: CalendarEvent }) {
  const start = parseISO(event.start_at);
  return (
    <div className='rounded-lg border bg-card p-3 text-sm shadow-sm'>
      <div className='flex items-start justify-between gap-2'>
        <div className='min-w-0 flex-1'>
          <div className='truncate font-medium'>{event.title}</div>
          {event.description && (
            <div className='mt-1 line-clamp-2 text-xs text-muted-foreground'>
              {event.description}
            </div>
          )}
        </div>
        <Badge variant={eventTypeVariant[event.event_type]}>{event.event_type}</Badge>
      </div>
      <div className='mt-2 text-xs text-muted-foreground'>
        {event.all_day ? 'All day' : format(start, 'h:mm a')}
      </div>
    </div>
  );
}
