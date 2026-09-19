import base from './playwright.config';

/** Ad-hoc config for running *.capture.ts evidence specs directly. */
export default {
  ...base,
  testMatch: '**/*.capture.ts',
  reporter: [['list']]
};
