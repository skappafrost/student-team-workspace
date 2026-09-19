import base from './playwright.config';

/**
 * Config for the QA evidence capture tool (`bun run qa:evidence`).
 * The capture spec lives in tests/ but is excluded from the check suite via
 * the base config's testMatch, so we point testMatch at it here.
 */
export default {
  ...base,
  testMatch: '**/qa-evidence.capture.ts',
  // Captures go to qa-evidence/, not the HTML report flow
  reporter: [['list']]
};
