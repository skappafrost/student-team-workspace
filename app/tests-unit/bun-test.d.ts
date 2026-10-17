/**
 * Ambient declarations for `bun test`.
 *
 * The runner is built into the bun binary that already installs this app's
 * dependencies, so `bun test` resolves `bun:test` at runtime with nothing to
 * install. The matching *types* live in the `@types/bun` package, which is not
 * a dependency here and cannot become one without touching `app/bun.lock` —
 * CI installs with `--frozen-lockfile`. `bun run typecheck` therefore needs
 * this file: without it every test reports TS2307 "Cannot find module
 * 'bun:test'".
 *
 * What this is not: a mirror of bun's API. It declares the matchers the suite
 * actually uses, so a matcher added here without being checked against
 * https://bun.com/docs/cli/test#expectations is a declaration that lies. When
 * `@types/bun` does land, delete this file rather than maintaining both.
 */
declare module 'bun:test' {
  interface Matchers<T> {
    /** Passes if `Object.is(actual, expected)` — reference equality for objects. */
    toBe(expected: T): void;
    /** Structural equality; `toStrictEqual` additionally checks prototypes. */
    toEqual(expected: T): void;
    toStrictEqual(expected: T): void;
    toBeUndefined(): void;
    toBeDefined(): void;
    toBeNull(): void;
    toBeTruthy(): void;
    toBeFalsy(): void;
    toBeNaN(): void;
    toBeGreaterThan(expected: number): void;
    toBeGreaterThanOrEqual(expected: number): void;
    toBeLessThan(expected: number): void;
    toBeLessThanOrEqual(expected: number): void;
    toBeCloseTo(expected: number, precision?: number): void;
    /** Membership: array element, substring, or `expect(string).toMatch(/re/)`. */
    toContain(expected: unknown): void;
    toMatch(expected: string | RegExp): void;
    toMatchObject(expected: object): void;
    toHaveLength(expected: number): void;
    toHaveProperty(key: string, value?: unknown): void;
    /** `actual` must be a function that throws. */
    toThrow(expected?: string | RegExp): void;
    readonly not: Matchers<T>;
    readonly resolves: Matchers<T>;
    readonly rejects: Matchers<T>;
  }

  function expect<T>(actual: T): Matchers<T>;

  function describe(name: string, fn: () => void): void;

  function it(name: string, fn: () => void | Promise<void>, timeout?: number): void;
  const test: typeof it;

  function beforeAll(fn: () => void | Promise<void>, timeout?: number): void;
  function afterAll(fn: () => void | Promise<void>, timeout?: number): void;
  function beforeEach(fn: () => void | Promise<void>, timeout?: number): void;
  function afterEach(fn: () => void | Promise<void>, timeout?: number): void;
}
