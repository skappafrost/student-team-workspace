'use client';

// Source: ThreeUI SylvaHero (variant "living-green"), trimmed to the registered
// bundle. The full LandingPages.tsx catalogs many pages whose sibling modules
// (tidecrest, meridian, axonis, …) are not part of the SylvaHero bundle, so the
// component is hoisted here unchanged for the living-green variant.
// Canonical scene: /landing-pages/inner-green-3d.html (byte-exact source).

import { splitTypographyProps, usePageTypography, type PageTypographyProps } from './pageTypography';
import { LandingPageFrame, type LandingPageProps } from './LandingPageFrame';
import { SYLVA_TYPOGRAPHY } from './pageRecipes';

export const SYLVA_HERO_VARIANTS = ['living-green'] as const;
export type SylvaHeroVariant = (typeof SYLVA_HERO_VARIANTS)[number];

export type SylvaHeroProps = LandingPageProps &
  PageTypographyProps & { variant?: SylvaHeroVariant };

export function SylvaHero({ variant = 'living-green', ...props }: SylvaHeroProps) {
  const safeVariant = SYLVA_HERO_VARIANTS.includes(variant) ? variant : 'living-green';
  const [type, frame] = splitTypographyProps(props);
  const customization = usePageTypography(SYLVA_TYPOGRAPHY, type);

  return (
    <LandingPageFrame
      {...frame}
      key={safeVariant}
      customization={customization}
      title='Teamspace — Your study team, one workspace'
      sourceUrl='/landing-pages/inner-green-3d.html'
    />
  );
}
