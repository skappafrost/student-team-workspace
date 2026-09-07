import { FileUploader } from '@/features/files/components/file-uploader';
import { FileList } from '@/features/files/components/file-list';
import PageContainer from '@/components/layout/page-container';
import { Suspense } from 'react';
import { getCurrentWorkspace } from '@/features/workspace/api/server';
import { NoWorkspaceState } from '@/features/workspace/components/no-workspace-state';

export const metadata = {
  title: 'Files',
  description: 'Workspace file uploads'
};

export default async function FilesPage() {
  const workspace = await getCurrentWorkspace();

  if (!workspace) {
    return (
      <PageContainer pageTitle='Files' pageDescription='Upload and manage workspace files.'>
        <NoWorkspaceState
          title='No workspace'
          description='Create or join a workspace before uploading files.'
        />
      </PageContainer>
    );
  }

  return (
    <PageContainer pageTitle='Files' pageDescription='Upload and manage workspace files.'>
      <div className='space-y-4'>
        <div className='flex justify-end'>
          <FileUploader />
        </div>
        <Suspense fallback={<div className='text-sm text-muted-foreground'>Loading files…</div>}>
          <FileList />
        </Suspense>
      </div>
    </PageContainer>
  );
}
