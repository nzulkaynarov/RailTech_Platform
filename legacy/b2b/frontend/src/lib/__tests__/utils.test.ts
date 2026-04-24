import { describe, it, expect } from 'vitest';
import { cn } from '../utils';

describe('cn (className merger)', () => {
  it('should merge class names', () => {
    expect(cn('foo', 'bar')).toBe('foo bar');
  });

  it('should handle conditional classes', () => {
    expect(cn('base', false && 'hidden', 'extra')).toBe('base extra');
  });

  it('should handle undefined and null', () => {
    expect(cn('base', undefined, null, 'end')).toBe('base end');
  });

  it('should resolve Tailwind conflicts', () => {
    // twMerge resolves conflicting Tailwind classes
    const result = cn('p-4', 'p-2');
    expect(result).toBe('p-2');
  });

  it('should resolve complex Tailwind conflicts', () => {
    const result = cn('text-red-500', 'text-blue-500');
    expect(result).toBe('text-blue-500');
  });

  it('should handle empty input', () => {
    expect(cn()).toBe('');
  });

  it('should handle array-style clsx input', () => {
    expect(cn(['foo', 'bar'])).toBe('foo bar');
  });

  it('should handle object-style clsx input', () => {
    expect(cn({ foo: true, bar: false, baz: true })).toBe('foo baz');
  });
});
