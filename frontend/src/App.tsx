import { useEffect } from 'react'
import { Navigate, Route, Routes, useNavigate } from 'react-router'
import { Toaster } from 'sonner'
import { AppShell } from '@/components/layout/AppShell'
import { RequireAuth } from '@/components/layout/RequireAuth'
import { setUnauthorizedHandler } from '@/lib/api'
import Login from '@/pages/Login'
import { useTheme } from '@/stores/theme'
import { ChatStub, DashboardStub, LaboratoryStub, OnboardingStub, RoadmapStub, VaultStub } from '@/pages/Stubs'

export default function App() {
  const navigate = useNavigate()
  const theme = useTheme((s) => s.theme)
  useEffect(() => {
    // The API refused our token: the session is over, so go to sign in.
    setUnauthorizedHandler(() => navigate('/login', { replace: true }))
  }, [navigate])

  return (
    <>
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppShell />}>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<DashboardStub />} />
          <Route path="/vault" element={<VaultStub />} />
          <Route path="/chat" element={<ChatStub />} />
          <Route path="/roadmap" element={<RoadmapStub />} />
          <Route path="/laboratory" element={<LaboratoryStub />} />
          <Route path="/onboarding" element={<OnboardingStub />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
    <Toaster position="bottom-right" theme={theme} richColors closeButton />
    </>
  )
}
