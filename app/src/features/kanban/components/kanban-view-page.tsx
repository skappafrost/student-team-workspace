'use client';

import { useState } from 'react';
import PageContainer from '@/components/layout/page-container';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { useProjects } from '@/features/projects/hooks/use-projects';
import { Project } from '@/features/projects/types';
import { KanbanBoard } from './kanban-board';
import NewTaskDialog from './new-task-dialog';

export default function KanbanViewPage() {
  const { projects, isLoading } = useProjects();
  const [selectedProjectId, setSelectedProjectId] = useState<string>('');

  return (
    <PageContainer
      pageTitle='Kanban'
      pageDescription='Manage tasks with drag and drop'
      pageHeaderAction={
        <div className='flex items-center gap-2'>
          <ProjectSelect
            projects={projects}
            selectedProjectId={selectedProjectId}
            onChange={setSelectedProjectId}
            isLoading={isLoading}
          />
          <NewTaskDialog onSubmit={() => {}} />
        </div>
      }
    >
      {selectedProjectId ? (
        <KanbanBoard key={selectedProjectId} projectId={selectedProjectId} />
      ) : (
        <EmptyState projects={projects} isLoading={isLoading} onSelect={setSelectedProjectId} />
      )}
    </PageContainer>
  );
}

interface ProjectSelectProps {
  projects: Project[];
  selectedProjectId: string;
  isLoading: boolean;
  onChange: (projectId: string) => void;
}

function ProjectSelect({ projects, selectedProjectId, isLoading, onChange }: ProjectSelectProps) {
  if (isLoading) {
    return <div className='text-muted-foreground text-sm'>Loading projects...</div>;
  }
  return (
    <Select value={selectedProjectId} onValueChange={(value) => onChange(value ?? '')}>
      <SelectTrigger className='w-[200px]'>
        <SelectValue placeholder='Select project' />
      </SelectTrigger>
      <SelectContent>
        {projects.map((project) => (
          <SelectItem key={project.id} value={project.id}>
            {project.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

interface EmptyStateProps {
  projects: Project[];
  isLoading: boolean;
  onSelect: (projectId: string) => void;
}

function EmptyState({ projects, isLoading, onSelect }: EmptyStateProps) {
  if (isLoading) {
    return <div className='text-muted-foreground text-sm'>Loading projects...</div>;
  }
  if (projects.length === 0) {
    return (
      <div className='text-muted-foreground text-sm'>
        No projects available. Create a project first.
      </div>
    );
  }
  return (
    <div className='flex flex-col items-center gap-2 rounded-md border border-dashed p-8 text-center'>
      <p className='text-sm text-muted-foreground'>Select a project to view its kanban board.</p>
      <div className='flex flex-wrap justify-center gap-2'>
        {projects.slice(0, 5).map((project) => (
          <Button key={project.id} variant='outline' size='sm' onClick={() => onSelect(project.id)}>
            {project.name}
          </Button>
        ))}
      </div>
    </div>
  );
}
