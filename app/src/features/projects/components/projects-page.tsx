'use client';

import { useEffect, useState } from 'react';
import PageContainer from '@/components/layout/page-container';
import { ProjectList } from './project-list';
import { CreateProjectDialog } from './create-project-dialog';
import { getProjects, createProject } from '../service';
import { Project, ProjectStatus, CreateProjectPayload } from '../types';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';

const STATUS_FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'active', label: 'Active' },
  { value: 'completed', label: 'Completed' },
  { value: 'archived', label: 'Archived' }
] as const;

type StatusFilter = (typeof STATUS_FILTERS)[number]['value'];

function StatusFilterRail({
  value,
  onChange,
  projects
}: {
  value: StatusFilter;
  onChange: (value: StatusFilter) => void;
  projects: Project[];
}) {
  const counts: Record<StatusFilter, number> = {
    all: projects.length,
    active: projects.filter((p) => p.status === 'active').length,
    completed: projects.filter((p) => p.status === 'completed').length,
    archived: projects.filter((p) => p.status === 'archived').length
  };

  return (
    <nav aria-label='Filter projects by status' className='flex flex-col gap-0.5'>
      <p className='text-muted-foreground mb-1 px-2 text-xs font-semibold tracking-wide uppercase'>
        Status
      </p>
      {STATUS_FILTERS.map((filter) => (
        <button
          key={filter.value}
          type='button'
          aria-current={value === filter.value ? 'true' : undefined}
          onClick={() => onChange(filter.value)}
          className={cn(
            'flex items-center justify-between rounded-md px-2 py-1.5 text-sm transition-colors',
            value === filter.value
              ? 'bg-accent text-accent-foreground font-medium'
              : 'text-muted-foreground hover:bg-muted hover:text-foreground'
          )}
        >
          {filter.label}
          <span className='text-muted-foreground text-xs tabular-nums'>{counts[filter.value]}</span>
        </button>
      ))}
    </nav>
  );
}

function ViewToggle({
  value,
  onChange
}: {
  value: 'grid' | 'list';
  onChange: (value: 'grid' | 'list') => void;
}) {
  return (
    <div
      role='tablist'
      aria-label='Project view'
      className='bg-muted flex w-fit rounded-full p-0.5'
    >
      {(['grid', 'list'] as const).map((v) => (
        <button
          key={v}
          type='button'
          role='tab'
          aria-selected={value === v}
          onClick={() => onChange(v)}
          className={cn(
            'rounded-full px-3.5 py-1 text-xs font-medium capitalize transition-colors',
            value === v
              ? 'bg-background text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground'
          )}
        >
          {v}
        </button>
      ))}
    </div>
  );
}

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [view, setView] = useState<'grid' | 'list'>('grid');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const filteredProjects =
    statusFilter === 'all'
      ? projects
      : projects.filter((project) => project.status === (statusFilter as ProjectStatus));

  useEffect(() => {
    let isMounted = true;
    void (async () => {
      setIsLoading(true);
      setLoadError(null);
      try {
        const data = await getProjects();
        if (!isMounted) return;
        setProjects(data);
      } catch (err) {
        if (!isMounted) return;
        setLoadError(err instanceof Error ? err.message : 'Failed to load projects');
      } finally {
        if (isMounted) setIsLoading(false);
      }
    })();
    return () => {
      isMounted = false;
    };
  }, [reloadKey]);

  const handleCreate = async (payload: CreateProjectPayload) => {
    setIsSubmitting(true);
    try {
      const project = await createProject(payload);
      setProjects((prev) => [...prev, project]);
      toast.success('Project created');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to create project');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <PageContainer
      pageTitle='Projects'
      pageDescription='Manage projects for this workspace.'
      pageHeaderAction={<CreateProjectDialog onSubmit={handleCreate} isSubmitting={isSubmitting} />}
    >
      <div className='flex flex-col gap-6 sm:flex-row'>
        <aside className='shrink-0 sm:w-44'>
          <StatusFilterRail
            value={statusFilter}
            onChange={setStatusFilter}
            projects={projects}
          />
        </aside>
        <div className='min-w-0 flex-1'>
          <div className='mb-4 flex justify-end'>
            <ViewToggle value={view} onChange={setView} />
          </div>
          {loadError ? (
            <div
              role='alert'
              className='border-destructive/30 bg-destructive/5 flex items-start gap-3 rounded-lg border p-4'
            >
              <Icons.alertCircle className='text-destructive mt-0.5 size-5 shrink-0' />
              <div className='flex-1'>
                <p className='text-sm font-medium'>Could not load projects</p>
                <p className='text-muted-foreground text-sm'>{loadError}</p>
              </div>
              <Button variant='outline' size='sm' onClick={() => setReloadKey((k) => k + 1)}>
                Retry
              </Button>
            </div>
          ) : !isLoading && projects.length > 0 && filteredProjects.length === 0 ? (
            <p className='text-muted-foreground py-12 text-center text-sm'>
              No {statusFilter} projects in this workspace.
            </p>
          ) : (
            <ProjectList
              projects={filteredProjects}
              isLoading={isLoading}
              view={view}
              emptyAction={
                <CreateProjectDialog onSubmit={handleCreate} isSubmitting={isSubmitting} />
              }
            />
          )}
        </div>
      </div>
    </PageContainer>
  );
}
