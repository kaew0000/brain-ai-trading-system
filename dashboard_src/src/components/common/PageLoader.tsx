import { motion } from 'framer-motion'

/**
 * Suspense fallback for React.lazy code-split routes.
 */
export default function PageLoader() {
  return (
    <div className="h-screen flex items-center justify-center bg-surface">
      <motion.div
        className="flex flex-col items-center gap-3"
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
      >
        <div className="w-8 h-8 border-2 border-accent-blue/30 border-t-accent-blue rounded-full animate-spin" />
        <span className="text-xs text-text-muted font-mono tracking-wider">LOADING MODULE…</span>
      </motion.div>
    </div>
  )
}
