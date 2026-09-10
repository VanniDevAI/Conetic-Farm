import { describe, expect, it } from 'vitest'

import { describeMultipleOf, isMultipleOf } from './hints.js'

describe('isMultipleOf', () => {
  it('accepts whole multiples', () => {
    expect(isMultipleOf(10, 5)).toBe(true)
    expect(isMultipleOf(1.5, 0.5)).toBe(true)
  })

  it('accepts decimal multiples the binary quotient cannot represent', () => {
    expect(isMultipleOf(2.03, 0.07)).toBe(true)
  })

  it('rejects values between multiples', () => {
    expect(isMultipleOf(1.2, 0.5)).toBe(false)
  })
})

describe('describeMultipleOf', () => {
  it('says which way it went', () => {
    expect(describeMultipleOf(10, 5)).toBe('10 is a multiple of 5')
    expect(describeMultipleOf(1.2, 0.5)).toBe('1.2 is not a multiple of 0.5')
  })
})
