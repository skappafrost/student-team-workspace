'use client';

import Link from 'next/link';
import { useMemo } from 'react';
import { useQueries, useQuery } from '@tanstack/react-query';
import {
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  XAxis,
  YAxis
} from 'recharts';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { Badge } from '@/components/ui/badge';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from '@/components/ui/card';
import { ChartContainer, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart';
import { Skeleton } from '@/components/ui/skeleton';
import { projectsQueryOptions } from '@/features/projects/queries';
import { tasksQueryOptions } from '@/features/kanban/api/queries';
import { notificationsQueryOptions } from '@/features/notifications/api/queries';
import { activityQueryOptions } from '@/features/activity/api/queries';
import { useWorkspace } from '@/features/workspace/hooks/use-workspace';
import { useWorkspaceMembers } from '@/features/workspace/hooks/use-workspace-members';
import type { TaskStatus } from '@/features/kanban/api/types';

const STATUS_LABELS: Record<TaskStatus, string> = {
  backlog: 'Backlog',
  todo: 'To do',
  doing: 'Doing',
  done: 'Done'
};

const PRIORITY_COLORS: Record<string, string> = {
  urgent: 'var(--color-chart-1)',
  high: 'var(--color-chart-3)',
  medium: 'var(--color-chart-2)',
  low: 'var(--color-chart-4)'
};

export default function OverviewDashboard() {
  const workspace = useWorkspace();
  const projectsQuery = useQuery(projectsQueryOptions());
  const projects = projectsQuery.data ?? [];

  const taskQueries = useQueries({
    queries: projects.map((p) => tasksQueryOptions(p.id))
  });
  const tasksLoading = taskQueries.some((q) => q.isLoading);
  const tasks = useMemo(
    () => taskQueries.flatMap((q) => q.data ?? []),
    [taskQueries]
  );

  const notificationsQuery = useQuery(notificationsQueryOptions());
  const notifications = notificationsQuery.data ?? [];
  const unreadCount = notifications.filter((n) => n.status === 'unread').length;

  const { members, isLoading: membersLoading } = useWorkspaceMembers();

  const isLoading = projectsQuery.isLoading || tasksLoading;
  const openTasks = tasks.filter((t) => t.status !== 'done');
  const doneTasks = tasks.filter((t) => t.status === 'done');
  const completionPct =
    tasks.length > 0 ? Math.round((doneTasks.length / tasks.length) * 100) : 0;

  const statusData = (Object.keys(STATUS_LABELS) as TaskStatus[]).map((s) => ({
    status: STATUS_LABELS[s],
    count: tasks.filter((t) => t.status === s).length
  }));

  const priorityData = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const t of openTasks) counts[t.priority] = (counts[t.priority] ?? 0) + 1;
    return Object.entries(counts).map(([priority, count]) => ({
      priority,
      count,
      fill: PRIORITY_COLORS[priority] ?? 'var(--color-chart-4)'
    }));
  }, [openTasks]);

  const activityQuery = useQuery(activityQueryOptions());
  const activity = (activityQuery.data ?? []).slice(0, 8);

  return (
    <PageContainer>
      <div className='flex flex-1 flex-col gap-4'>
        <div className='flex items-center justify-between'>
          <h1 className='text-2xl font-bold tracking-tight'>
            {workspace.data?.name ? `${workspace.data.name} overview` : 'Overview'}
          </h1>
          <Badge variant='outline' className='gap-1'>
            <Icons.circleCheck className='size-3.5' />
            {completionPct}% complete
          </Badge>
        </div>

        <div className='grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4'>
          <StatCard
            label='Open tasks'
            value={openTasks.length}
            icon={<Icons.forms className='text-muted-foreground size-4' />}
            loading={isLoading}
          />
          <StatCard
            label='Completed'
            value={doneTasks.length}
            icon={<Icons.circleCheck className='text-muted-foreground size-4' />}
            loading={isLoading}
          />
          <StatCard
            label='Unread notifications'
            value={unreadCount}
            icon={<Icons.notification className='text-muted-foreground size-4' />}
            loading={notificationsQuery.isLoading}
          />
          <StatCard
            label='Team members'
            value={members.length}
            icon={<Icons.teams className='text-muted-foreground size-4' />}
            loading={membersLoading}
          />
        </div>

        {projects.length === 0 && !projectsQuery.isLoading ? (
          <Card className='border-dashed'>
            <CardHeader>
              <CardTitle>No projects yet</CardTitle>
              <CardDescription>
                Create a project on the kanban board to start tracking team tasks.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Link
                href='/dashboard/kanban'
                className='text-primary text-sm font-medium hover:underline'
              >
                Go to kanban
              </Link>
            </CardContent>
          </Card>
        ) : (
          <div className='grid grid-cols-1 gap-4 lg:grid-cols-7'>
            <Card className='lg:col-span-4'>
              <CardHeader>
                <CardTitle>Tasks by status</CardTitle>
                <CardDescription>Across all projects in this workspace</CardDescription>
              </CardHeader>
              <CardContent>
                <ChartContainer
                  config={{ count: { label: 'Tasks', color: 'var(--color-chart-1)' } }}
                  className='h-[250px] w-full'
                >
                  <BarChart data={statusData} accessibilityLayer>
                    <XAxis dataKey='status' tickLine={false} axisLine={false} />
                    <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={28} />
                    <ChartTooltip content={<ChartTooltipContent />} />
                    <Bar dataKey='count' fill='var(--color-chart-1)' radius={4} />
                  </BarChart>
                </ChartContainer>
              </CardContent>
            </Card>

            <Card className='lg:col-span-3'>
              <CardHeader>
                <CardTitle>Open tasks by priority</CardTitle>
                <CardDescription>What needs attention first</CardDescription>
              </CardHeader>
              <CardContent>
                {priorityData.length === 0 ? (
                  <p className='text-muted-foreground py-16 text-center text-sm'>
                    No open tasks. Nothing on fire.
                  </p>
                ) : (
                  <ChartContainer
                    config={{ count: { label: 'Tasks' } }}
                    className='mx-auto h-[250px] w-full'
                  >
                    <PieChart>
                      <ChartTooltip content={<ChartTooltipContent hideLabel />} />
                      <Pie
                        data={priorityData}
                        dataKey='count'
                        nameKey='priority'
                        innerRadius={55}
                        outerRadius={90}
                        strokeWidth={2}
                      >
                        {priorityData.map((d) => (
                          <Cell key={d.priority} fill={d.fill} />
                        ))}
                      </Pie>
                    </PieChart>
                  </ChartContainer>
                )}
                {priorityData.length > 0 && (
                  <div className='mt-2 flex flex-wrap justify-center gap-3'>
                    {priorityData.map((d) => (
                      <span
                        key={d.priority}
                        className='text-muted-foreground flex items-center gap-1.5 text-xs capitalize'
                      >
                        <span
                          className='size-2.5 rounded-sm'
                          style={{ backgroundColor: d.fill }}
                        />
                        {d.priority} ({d.count})
                      </span>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className='lg:col-span-7'>
              <CardHeader>
                <CardTitle>Recent activity</CardTitle>
                <CardDescription>What the team has been up to</CardDescription>
              </CardHeader>
              <CardContent>
                {activity.length === 0 ? (
                  <p className='text-muted-foreground py-8 text-center text-sm'>
                    No activity yet. Create a task, event or page to get things moving.
                  </p>
                ) : (
                  <ul className='divide-border divide-y'>
                    {activity.map((a) => (
                      <li key={a.id} className='flex items-start gap-3 py-3 first:pt-0 last:pb-0'>
                        <span className='bg-primary mt-1.5 size-2 shrink-0 rounded-full' />
                        <div className='min-w-0 flex-1'>
                          <p className='truncate text-sm font-medium'>
                            <span className='font-semibold'>{a.actor_name}</span> {a.verb}{' '}
                            {a.target_label ? (
                              <span className='text-foreground'>{a.target_label}</span>
                            ) : (
                              a.target_type
                            )}
                          </p>
                        </div>
                        <time className='text-muted-foreground shrink-0 text-xs'>
                          {new Date(a.created_at).toLocaleDateString()}
                        </time>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>
        )}
      </div>
    </PageContainer>
  );
}

function StatCard({
  label,
  value,
  icon,
  loading
}: {
  label: string;
  value: number;
  icon: React.ReactNode;
  loading: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardDescription className='flex items-center gap-2'>
          {icon}
          {label}
        </CardDescription>
        {loading ? (
          <Skeleton className='h-8 w-16' />
        ) : (
          <CardTitle className='text-3xl font-semibold tabular-nums'>{value}</CardTitle>
        )}
      </CardHeader>
    </Card>
  );
}
