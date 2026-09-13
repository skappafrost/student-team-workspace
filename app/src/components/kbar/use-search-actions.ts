'use client';

import { useKBar, useRegisterActions, type Action } from 'kbar';
import * as React from 'react';
import { Icons } from '@/components/icons';
import { getMyTasks } from '@/features/deadlines/service';
import { getProjects } from '@/features/projects/service';
import { searchPages } from '@/features/wiki/api/service';

export const SEARCH_CAP = 20;

const relativeTime = (iso?: string): string => {
  if (!iso) return '';
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
};

/**
 * U04: data search inside kbar. When the query is 2+ chars, searches tasks,
 * projects and wiki pages and registers them as kbar actions (capped at
 * SEARCH_CAP) with kind icons and relative timestamps.
 */
export function useSearchActions(routerPush: (url: string) => void) {
  const { searchQuery } = useKBar((state) => ({ searchQuery: state.searchQuery }));
  const [results, setResults] = React.useState<{ actions: Action[]; capped: boolean }>({
    actions: [],
    capped: false
  });

  React.useEffect(() => {
    const query = searchQuery.trim();
    if (query.length < 2) {
      setResults({ actions: [], capped: false });
      return;
    }

    let cancelled = false;
    const timer = setTimeout(async () => {
      const [tasks, projects, pages] = await Promise.all([
        getMyTasks().catch(() => []),
        getProjects().catch(() => []),
        searchPages(query).catch(() => [])
      ]);
      if (cancelled) return;

      const lower = query.toLowerCase();
      const taskActions: Action[] = tasks
        .filter((t) => t.title.toLowerCase().includes(lower))
        .map((t) => ({
          id: `search-task-${t.id}`,
          name: t.title,
          keywords: t.title.toLowerCase(),
          section: 'Tasks',
          subtitle: `${t.project_name} · ${relativeTime(t.updated_at)}`,
          icon: React.createElement(Icons.kanban, { className: 'h-4 w-4' }),
          perform: () => routerPush('/dashboard/kanban')
        }));
      const projectActions: Action[] = projects
        .filter((p) => p.name.toLowerCase().includes(lower))
        .map((p) => ({
          id: `search-project-${p.id}`,
          name: p.name,
          keywords: p.name.toLowerCase(),
          section: 'Projects',
          subtitle: `Project · ${relativeTime(p.updated_at)}`,
          icon: React.createElement(Icons.dashboard, { className: 'h-4 w-4' }),
          perform: () => routerPush(`/dashboard/kanban?project=${p.id}`)
        }));
      const pageActions: Action[] = pages.map((p) => ({
        id: `search-page-${p.id}`,
        name: p.title,
        keywords: p.title.toLowerCase(),
        section: 'Wiki',
        subtitle: 'Wiki page',
        icon: React.createElement(Icons.page, { className: 'h-4 w-4' }),
        perform: () => routerPush('/dashboard/wiki')
      }));

      const all = [...taskActions, ...projectActions, ...pageActions];
      setResults({ actions: all.slice(0, SEARCH_CAP), capped: all.length > SEARCH_CAP });
    }, 250);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [searchQuery, routerPush]);

  useRegisterActions(results.actions, [results.actions]);

  return results.capped;
}
