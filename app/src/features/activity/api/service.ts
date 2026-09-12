import type { ActivityItem } from './types';

export async function getActivity(): Promise<ActivityItem[]> {
  const res = await fetch('/api/activity', { cache: 'no-store' });
  if (!res.ok) return [];
  const data = (await res.json()) as { activities?: ActivityItem[] };
  return data.activities ?? [];
}
