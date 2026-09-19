import { render, screen } from '@testing-library/react';

import { AvatarStack } from './avatar-stack';

const users = [
  { name: 'Alice Alpha' },
  { name: 'Bob Beta' },
  { name: 'Cara Chi' },
  { name: 'Dan Delta' },
  { name: 'Eve Echo' },
  { name: 'Finn Foxtrot' }
];

describe('AvatarStack', () => {
  it('renders initials for each user', () => {
    render(<AvatarStack users={users.slice(0, 3)} />);
    expect(screen.getByText('AA')).toBeInTheDocument();
    expect(screen.getByText('BB')).toBeInTheDocument();
    expect(screen.getByText('CC')).toBeInTheDocument();
  });

  it('caps at max and shows +N overflow', () => {
    render(<AvatarStack users={users} max={4} />);
    expect(screen.getByText('+2')).toBeInTheDocument();
    expect(screen.queryByText('EE')).not.toBeInTheDocument();
  });

  it('hides overflow pill when all users fit', () => {
    render(<AvatarStack users={users.slice(0, 2)} />);
    expect(screen.queryByText(/^\+/)).not.toBeInTheDocument();
  });

  it('renders nothing extra for empty list', () => {
    const { container } = render(<AvatarStack users={[]} />);
    expect(container.querySelectorAll('[data-slot="avatar"]').length).toBe(0);
  });
});
