import { useRef, useCallback } from 'react'

/**
 * Debounce hook — delays fn execution until `ms` after the last call.
 */
export function useDebounce<T extends (...args: any[]) => void>(fn: T, ms: number): T {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  return useCallback((...args: Parameters<T>) => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => fn(...args), ms)
  }, [fn, ms]) as T
}
