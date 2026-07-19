import { useRef, useCallback } from 'react'

/**
 * Throttle hook — guarantees fn fires at most once per `ms`.
 * Also queues a trailing call if invoked during the cooldown window.
 */
export function useThrottle<T extends (...args: any[]) => void>(fn: T, ms: number): T {
  const last = useRef(0)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  return useCallback((...args: Parameters<T>) => {
    const now = Date.now()
    if (now - last.current >= ms) {
      last.current = now
      fn(...args)
    } else if (!timer.current) {
      timer.current = setTimeout(() => {
        last.current = Date.now()
        timer.current = null
        fn(...args)
      }, ms - (now - last.current))
    }
  }, [fn, ms]) as T
}
