export type CalendarEventType = 'deadline' | 'exam' | 'meeting' | 'reminder';
export type Recurrence = 'none' | 'daily' | 'weekly' | 'monthly';

export interface CalendarEvent {
  id: string;
  workspace_id: string;
  project_id: string | null;
  created_by: string;
  title: string;
  description: string | null;
  start_at: string;
  end_at: string | null;
  all_day: boolean;
  event_type: CalendarEventType;
  recurrence: Recurrence;
  /** Set on expanded occurrences of a recurring event (unique per instance). */
  occurrence_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateEventPayload {
  title: string;
  description?: string | null;
  start_at: string;
  end_at?: string | null;
  all_day?: boolean;
  event_type?: CalendarEventType;
  recurrence?: Recurrence;
  project_id?: string | null;
}

export interface UpdateEventPayload {
  title?: string;
  description?: string | null;
  start_at?: string;
  end_at?: string | null;
  all_day?: boolean;
  event_type?: CalendarEventType;
  recurrence?: Recurrence;
  project_id?: string | null;
}

export interface EventFilters {
  start?: string;
  end?: string;
}
