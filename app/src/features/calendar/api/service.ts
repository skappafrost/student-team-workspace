import { CalendarEvent, CreateEventPayload, EventFilters, UpdateEventPayload } from './types';
import { createApiClient } from '@/lib/api-client';

const apiRequest = createApiClient('/api/events');


export async function getEvents(filters?: EventFilters): Promise<CalendarEvent[]> {
  const params = new URLSearchParams();
  if (filters?.start) params.set('start', filters.start);
  if (filters?.end) params.set('end', filters.end);
  const query = params.toString();
  const data = await apiRequest<{ events: CalendarEvent[] }>(query ? `?${query}` : '');
  return data.events || [];
}

export async function createEvent(payload: CreateEventPayload): Promise<CalendarEvent> {
  const data = await apiRequest<{ event: CalendarEvent }>('', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
  return data.event;
}

export async function updateEvent(id: string, payload: UpdateEventPayload): Promise<CalendarEvent> {
  const data = await apiRequest<{ event: CalendarEvent }>('', {
    method: 'PATCH',
    body: JSON.stringify({ eventId: id, ...payload })
  });
  return data.event;
}

export async function deleteEvent(id: string): Promise<void> {
  await apiRequest<{ ok: boolean }>(`?eventId=${encodeURIComponent(id)}`, {
    method: 'DELETE'
  });
}
