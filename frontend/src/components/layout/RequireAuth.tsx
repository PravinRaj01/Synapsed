import { Navigate, Outlet, useLocation } from 'react-router'
import { useSession } from '@/lib/session'
import { Logo } from './Logo'

/** Everything inside needs a signed-in user; anyone else is sent to sign in and brought back afterwards. */
export function RequireAuth() {
  const { data: user, isLoading } = useSession()
  const location = useLocation()
  if (isLoading) {
    return (
      <div className="grid min-h-dvh place-items-center bg-canvas" role="status" aria-label="Loading">
        <Logo className="animate-pulse" />
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <Outlet />
}
