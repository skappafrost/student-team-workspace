'use client';

import { useEffect, useState } from 'react';
import PageContainer from '@/components/layout/page-container';
import { ProjectList } from './project-list';
import { CreateProjectDialog } from './create-project-dialog';
import { getProjects, createProject } from '../service';
import { Project, CreateProjectPayload } from '../types';
import { toast } from 'sonner';

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    let isMounted = true;
    void (async () => {
      setIsLoading(true);
      try {
        const data = await getProjects();
        if (!isMounted) return;
        setProjects(data);
      } catch (err) {
        if (!isMounted) return;
        toast.error(err instanceof Error ? err.message : 'Failed to load projects');
      } finally {
        if (isMounted) setIsLoading(false);
      }
    })();
    return () => {
      isMounted = false;
    };
  }, []);

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
      <ProjectList projects={projects} isLoading={isLoading} />
    </PageContainer>
  );
}
