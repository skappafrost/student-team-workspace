'use client';

import { useQuery } from '@tanstack/react-query';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { Badge } from '@/components/ui/badge';
import { myTasksQueryOptions } from '../queries';
import { DueBucket, MyTask } from '../types';

const DAY_MS = 24 * 60 * 60 * 1000;

function bucketOf(task: MyTask, now: Date): DueBucket {
  if (!task.due_at) return 'none';
  const due = new Date(task.due_at);
  const todayEnd = new Date(now);
  todayEnd.setHours(23, 59, 59, 999);
  const weekEnd = new Date(todayEnd.getTime() + 7 * DAY_MS);
  if (due < now) return 'overdue';
  if (due <= todayEnd) return 'today';
  if (due <= weekEnd) return 'week';
  return 'later';
}

const SECTIONS: Array<{
  bucket: DueBucket;
  title: string;
  hint: string;
  accent: string;
}> = [
  {
    bucket: 'overdue',
    title: 'Overdue',
    hint: 'Past due — handle these first',
    accent: 'text-destructive'
  },
  { bucket: 'today', title: 'Today', hint: 'Due before midnight', accent: 'text-amber-600 dark:text-amber-400' },
  { bucket: 'week', title: 'This week', hint: 'Due within 7 days', accent: 'text-foreground' },
  { bucket: 'later', title: 'Later', hint: 'More than a week out', accent: 'text-muted-foreground' },
  { bucket: 'none', title: 'No date', hint: 'No due date set', accent: 'text-muted-foreground' }
];

function formatDue(due: string | null): string {
  if (!due) return '';
  const d = new Date(due);
  return d.toLocaleString(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  });
}

function TaskRow({ task }: { task: MyTask }) {
  return (
    <li className='flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border bg-card px-3 py-2'>
      <span className='text-sm font-medium'>{task.title}</span>
      <span className='text-muted-foreground text-xs'>
        {task.project_name} · {task.workspace_name}
      </span>
      <span className='ml-auto flex items-center gap-2'>
        <Badge variant='outline' className='capitalize'>
          {task.status}
        </Badge>
        {task.due_at ? (
          <span className='text-muted-foreground flex items-center gap-1 text-xs'>
            <Icons.clock className='size-3' />
            {formatDue(task.due_at)}
          </span>
        ) : null}
      </span>
    </li>
  );
}

export default function DeadlinesPage() {
  const { data: tasks = [], isPending, isError, error } = useQuery(myTasksQueryOptions());

  const now = new Date();
  const groups = new Map<DueBucket, MyTask[]>();
  for (const section of SECTIONS) groups.set(section.bucket, []);
  for (const task of tasks) {
    groups.get(bucketOf(task, now))?.push(task);
  }
  const open = tasks.filter((t) => t.status !== 'done');

  return (
    <PageContainer
      pageTitle='My deadlines'
      pageDescription='Everything assigned to you across all workspaces.'
    >
      {isPending ? (
        <div className='text-muted-foreground text-sm'>Loading your tasks…</div>
      ) : isError ? (
        <div className='text-destructive text-sm'>
          {error instanceof Error ? error.message : 'Failed to load tasks'}
        </div>
      ) : open.length === 0 ? (
        <div className='text-muted-foreground flex flex-col items-center gap-2 py-16 text-sm'>
          <Icons.calendar className='size-8' />
          Nothing on your plate. Enjoy the calm.
        </div>
      ) : (
        <div className='space-y-6'>
          {SECTIONS.map((section) => {
            const items = groups.get(section.bucket) ?? [];
            if (items.length === 0) return null;
            return (
              <section key={section.bucket}>
                <div className='mb-2 flex items-baseline gap-2'>
                  <h2 className={`text-sm font-semibold ${section.accent}`}>
                    {section.title}
                  </h2>
                  <span className='text-muted-foreground text-xs'>
                    {items.length} · {section.hint}
                  </span>
                </div>
                <ul className='space-y-2'>
                  {items.map((task) => (
                    <TaskRow key={task.id} task={task} />
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
      )}
    </PageContainer>
  );
}
