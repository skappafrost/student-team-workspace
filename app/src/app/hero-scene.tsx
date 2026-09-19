'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { SylvaHero } from '@/shaders/landing-pages/SylvaHero';
import '@/shaders/threeui.css';

export function HeroScene() {
  const router = useRouter();

  useEffect(() => {
    function onMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin) return;
      const data = event.data as { type?: string; href?: string } | undefined;
      if (data?.type === 'threeui:navigate' && typeof data.href === 'string') {
        router.push(data.href);
      }
    }
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [router]);

  return (
    <div className='shader-frame fixed inset-0'>
      <SylvaHero
        variant='living-green'
        headingFont='lexend'
        bodyFont='lexend'
        headingWeight='300'
        bodyWeight='300'
        primaryColor='#ffffff'
        headingSize={63}
        bodySize={16.5}
        headingLetterSpacing={-0.006}
      />
    </div>
  );
}
