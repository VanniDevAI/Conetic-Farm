import * as core from 'zod/v4/core'

/**
 * Whether `value` is a multiple of `step`.
 *
 * Uses zod's own float-safe comparison rather than `%`, so a form hint and the
 * schema that validates the same field can never disagree: `1.5 % 0.1` is not
 * zero in binary floating point even though 1.5 is a multiple of 0.1 in
 * decimal, and zod already solves that.
 */
export function isMultipleOf(value: number, step: number): boolean {
  return core.util.floatSafeRemainder(value, step) === 0
}

/**
 * The message a form shows under a `multipleOf` field.
 */
export function describeMultipleOf(value: number, step: number): string {
  return isMultipleOf(value, step)
    ? `${value} is a multiple of ${step}`
    : `${value} is not a multiple of ${step}`
}
