'use client';

import { useRef, useState } from 'react';
import { cn } from '@/lib/utils';

/**
 * 3D-tilt primary button. Adapted from uiverse.io/MuhammadHasann/quick-goose-5,
 * recolored to theme tokens (primary bg, foreground shadow).
 * The button rotates toward the cursor and casts a hard offset shadow
 * on the opposite side; presses down with scale(0.95).
 */
export function TiltButton({
  className,
  children,
  ...props
}: React.ComponentProps<'button'>) {
  const ref = useRef<HTMLButtonElement>(null);
  const [tilt, setTilt] = useState({ rx: 0, ry: 0, sx: 0, sy: 0 });

  const handleMove = (e: React.MouseEvent) => {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return;
    const x = (e.clientX - rect.left) / rect.width - 0.5; // -0.5..0.5
    const y = (e.clientY - rect.top) / rect.height - 0.5;
    setTilt({ rx: -y * 20, ry: x * 20, sx: x * 4, sy: y * 4 });
  };

  const reset = () => setTilt({ rx: 0, ry: 0, sx: 0, sy: 0 });

  return (
    <div className='inline-block [perspective:800px]'>
      <button
        ref={ref}
        type='button'
        data-slot='tilt-button'
        onMouseMove={handleMove}
        onMouseLeave={reset}
        style={{
          transform: `rotateX(${tilt.rx}deg) rotateY(${tilt.ry}deg)`,
          boxShadow:
            tilt.rx === 0 && tilt.ry === 0
              ? undefined
              : `${-tilt.sx}px ${-tilt.sy}px 0 oklch(0.21 0.02 265 / 0.45)`
        }}
        className={cn(
          'bg-primary text-primary-foreground inline-flex h-9 items-center justify-center gap-1.5 rounded-lg px-4 text-sm font-medium transition-transform duration-150 select-none active:scale-95 disabled:pointer-events-none disabled:opacity-50',
          className
        )}
        {...props}
      >
        {children}
      </button>
    </div>
  );
}
