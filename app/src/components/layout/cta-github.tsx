import { Icons } from '@/components/icons';

export default function CtaGithub() {
  return (
    <a
      aria-label='View on GitHub'
      href='https://github.com/Kiranism/next-shadcn-dashboard-starter'
      rel='noopener noreferrer'
      target='_blank'
      className='hidden items-center justify-center text-muted-foreground transition-colors duration-200 hover:text-foreground sm:flex'
    >
      <Icons.github className='transition-transform duration-200 group-hover:animate-bounce' />
    </a>
  );
}
