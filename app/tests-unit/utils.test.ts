/**
 * `cn` is the className merger the shadcn components call; the rule that makes
 * an override work is tailwind-merge's, not clsx's, and it is invisible in the
 * DOM until a class silently loses. `formatBytes` writes the size labels in
 * `src/components/file-uploader.tsx` and the share dialog. Both are pure, so
 * they can be pinned here instead of through a browser.
 */
import { describe, expect, it } from 'bun:test';

import { cn, formatBytes } from '@/lib/utils';

describe('cn', () => {
  it('lets the later utility win inside a Tailwind conflict group', () => {
    expect(cn('p-2', 'p-4')).toBe('p-4');
    // the shorthand `p-4` subsumes the longhand `px-2`, it does not sit beside it
    expect(cn('px-2', 'p-4')).toBe('p-4');
    expect(cn('bg-red-500', 'bg-blue-600')).toBe('bg-blue-600');
  });

  it('keeps non-conflicting utilities and drops falsy inputs', () => {
    // the leftovers a `cond && 'cls'` prop leaves in the argument list
    expect(cn('text-sm', false, null, undefined, 0, '', 'font-bold')).toBe('text-sm font-bold');
    expect(cn()).toBe('');
  });

  it('flattens the clsx inputs the components actually pass', () => {
    expect(cn(['a', { b: true, c: false }], 'd')).toBe('a b d');
  });
});

describe('formatBytes', () => {
  it('steps on 1024 and honours decimals and unit naming', () => {
    expect(formatBytes(123)).toBe('123 Bytes');
    expect(formatBytes(1024)).toBe('1 KB');
    expect(formatBytes(1536, { decimals: 1 })).toBe('1.5 KB');
    expect(formatBytes(1536, { decimals: 1, sizeType: 'accurate' })).toBe('1.5 KiB');
  });

  it('names zero bytes singularly, because Math.log(0) is -Infinity', () => {
    // the guard has to stay in front of the `i` computation or 0 renders "NaN Bytes"
    expect(formatBytes(0)).toBe('0 Byte');
  });
});
