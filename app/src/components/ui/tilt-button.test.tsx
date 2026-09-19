import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { TiltButton } from './tilt-button';

describe('TiltButton', () => {
  it('renders children and merges className', () => {
    render(<TiltButton className='w-full'>Create</TiltButton>);
    const btn = screen.getByRole('button', { name: 'Create' });
    expect(btn).toHaveClass('w-full');
  });

  it('tilts on mouse move and resets on leave', () => {
    render(<TiltButton>Hover me</TiltButton>);
    const btn = screen.getByRole('button', { name: 'Hover me' });
    // jsdom reports 0-size rects; stub a real one so tilt math is finite
    vi.spyOn(btn, 'getBoundingClientRect').mockReturnValue({
      left: 0,
      top: 0,
      width: 100,
      height: 40
    } as DOMRect);
    fireEvent.mouseMove(btn, { clientX: 75, clientY: 10 });
    expect(btn.style.transform).toContain('rotateX');
    expect(btn.style.boxShadow).not.toBe('');
    fireEvent.mouseLeave(btn);
    expect(btn.style.transform).toBe('rotateX(0deg) rotateY(0deg)');
    expect(btn.style.boxShadow).toBe('');
  });

  it('forwards onClick', async () => {
    const onClick = vi.fn();
    render(<TiltButton onClick={onClick}>Go</TiltButton>);
    await userEvent.click(screen.getByRole('button', { name: 'Go' }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it('respects disabled', async () => {
    const onClick = vi.fn();
    render(
      <TiltButton disabled onClick={onClick}>
        Nope
      </TiltButton>
    );
    const btn = screen.getByRole('button', { name: 'Nope' });
    expect(btn).toBeDisabled();
    await userEvent.click(btn);
    expect(onClick).not.toHaveBeenCalled();
  });
});
