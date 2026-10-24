import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { Navigate, Route, Routes, useNavigate } from 'react-router'
import { Toaster, toast } from 'sonner'
import { AppShell } from '@/components/layout/AppShell'
import { RequireAuth } from '@/components/layout/RequireAuth'
import { setUnauthorizedHandler } from '@/lib/api'
import { authClient } from '@/lib/auth'
import Login from '@/pages/Login'
import Dashboard from '@/pages/Dashboard'
import Onboarding from '@/pages/Onboarding'
import { ChatStub, LaboratoryStub, RoadmapStub, VaultStub } from '@/pages/Stubs'
import { useTheme } from '@/stores/theme'

export default function App() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const theme = useTheme((s) => s.theme)
  useEffect(() => {
    // The API refused a fresh token. Only treat the session as over if the auth service agrees; if it says we are
    // still signed in, the problem is on the server side, so say so instead of bouncing the user around.
    setUnauthorizedHandler(async () => {
      const { data } = await authClient.getSession().catch(() => ({ data: null }))
      if (data?.user) {
        toast.error('The server could not verify your sign-in. Please try again in a moment.', { id: 'unauthorized' })
        return
      }
      queryClient.clear()
      navigate('/login', { replace: true })
    })
  }, [navigate, queryClient])

  return (
    <>
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppShell />}>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/vault" element={<VaultStub />} />
          <Route path="/chat" element={<ChatStub />} />
          <Route path="/roadmap" element={<RoadmapStub />} />
          <Route path="/laboratory" element={<LaboratoryStub />} />
          <Route path="/onboarding" element={<Onboarding />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
    <Toaster position="bottom-right" theme={theme} richColors closeButton />
    </>
  )
}
