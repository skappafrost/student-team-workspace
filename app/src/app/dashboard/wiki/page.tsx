import WikiPage from '@/features/wiki/components/wiki-page';
import { getCurrentWorkspace } from '@/features/workspace/api/server';
import PageContainer from '@/components/layout/page-container';
import { NoWorkspaceState } from '@/features/workspace/components/no-workspace-state';

export const metadata = {
  title: 'Wiki',
  description: 'Workspace wiki pages'
};

export default async function WikiDashboardPage() {
  const workspace = await getCurrentWorkspace();

  if (!workspace) {
    return (
      <PageContainer pageTitle='Wiki' pageDescription='Browse workspace pages and documentation.'>
        <NoWorkspaceState
          title='No workspace'
          description='Create or join a workspace before creating wiki pages.'
        />
      </PageContainer>
    );
  }

  return <WikiPage />;
}
