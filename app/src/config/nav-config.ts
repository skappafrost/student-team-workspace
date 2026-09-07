import { NavGroup } from '@/types';

/**
 * Navigation configuration with RBAC support
 *
 * This configuration is used for both the sidebar navigation and Cmd+K bar.
 * Items are organized into groups, each rendered with a SidebarGroupLabel.
 */
export const navGroups: NavGroup[] = [
  {
    label: 'Overview',
    items: [
      {
        title: 'Overview',
        url: '/dashboard/overview',
        icon: 'dashboard',
        isActive: false,
        items: []
      }
    ]
  },
  {
    label: 'Projects',
    items: [
      {
        title: 'Projects',
        url: '/dashboard/projects',
        icon: 'kanban',
        isActive: false,
        items: []
      }
    ]
  },
  {
    label: 'Calendar',
    items: [
      {
        title: 'Calendar',
        url: '/dashboard/calendar',
        icon: 'calendar',
        isActive: false,
        items: []
      }
    ]
  },
  {
    label: 'Chat',
    items: [
      {
        title: 'Chat',
        url: '/dashboard/chat',
        icon: 'chat',
        isActive: false,
        items: []
      }
    ]
  },
  {
    label: 'Knowledge',
    items: [
      {
        title: 'Knowledge',
        url: '/dashboard/knowledge',
        icon: 'sparkles',
        isActive: false,
        items: []
      }
    ]
  },
  {
    label: 'Wiki',
    items: [
      {
        title: 'Wiki',
        url: '/dashboard/wiki',
        icon: 'wiki',
        isActive: false,
        items: []
      }
    ]
  },
  {
    label: 'Files',
    items: [
      {
        title: 'Files',
        url: '/dashboard/files',
        icon: 'workspace',
        isActive: false,
        items: []
      }
    ]
  },
  {
    label: 'Settings',
    items: [
      {
        title: 'Settings',
        url: '/dashboard/settings',
        icon: 'settings',
        isActive: false,
        items: []
      }
    ]
  }
];
