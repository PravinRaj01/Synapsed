import { useQueryClient } from '@tanstack/react-query'
import { motion } from 'motion/react'
import { Sparkles } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { Navigate, useLocation, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { z } from 'zod'
import { Logo } from '@/components/layout/Logo'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { warmUpApi } from '@/lib/api'
import { authClient } from '@/lib/auth'
import { useSession } from '@/lib/session'
import { zodResolver } from '@/lib/zodResolver'

const credentials = z.object({
  name: z.string().trim().optional(),
  email: z.email('Enter a valid email address'),
  password: z.string().min(8, 'Use at least 8 characters'),
})
type Credentials = z.infer<typeof credentials>
type Mode = 'signin' | 'signup'

const field = 'h-11 w-full rounded-full border border-line bg-inner px-4 text-sm text-ink outline-none placeholder:text-muted focus:border-accent'

export default function Login() {
  const { data: user } = useSession()
  const location = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [mode, setMode] = useState<Mode>('signin')
  const [pendingEmail, setPendingEmail] = useState<string | null>(null) // set while waiting for the emailed code
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const from = (location.state as { from?: string } | null)?.from ?? '/dashboard'

  const form = useForm<Credentials>({
    resolver: zodResolver(credentials),
    defaultValues: { name: '', email: '', password: '' },
  })

  // The API sleeps when idle and takes several seconds to wake. Wake it now, while the user is typing their password.
  useEffect(() => {
    warmUpApi()
  }, [])

  if (user) return <Navigate to={from} replace />

  async function finish() {
    await queryClient.invalidateQueries({ queryKey: ['session'] })
    navigate(from, { replace: true })
  }

  async function submit(values: Credentials) {
    setBusy(true)
    setError(null)
    try {
      if (mode === 'signup') {
        const name = values.name || values.email.split('@')[0]
        const { error } = await authClient.signUp.email({ name, email: values.email, password: values.password })
        if (error) throw new Error(error.message)
        setPendingEmail(values.email) // the service emails a code before the first sign-in
        toast.success('We emailed you a verification code.')
        return
      }
      const { error } = await authClient.signIn.email({ email: values.email, password: values.password })
      if (error) {
        if (error.code === 'EMAIL_NOT_VERIFIED') {
          await authClient.emailOtp.sendVerificationOtp({ email: values.email, type: 'email-verification' })
          setPendingEmail(values.email)
          toast.info('Please verify your email first. We sent you a new code.')
          return
        }
        throw new Error(error.message)
      }
      await finish()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  async function verify() {
    if (!pendingEmail) return
    setBusy(true)
    setError(null)
    try {
      const { error } = await authClient.emailOtp.verifyEmail({ email: pendingEmail, otp: code.trim() })
      if (error) throw new Error(error.message)
      const { data: session } = await authClient.getSession()
      if (session?.user) return await finish()
      setPendingEmail(null) // verified, but not signed in yet: ask for the password again
      setMode('signin')
      toast.success('Email verified. Please sign in.')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That code did not work. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  async function google() {
    setError(null)
    const { error } = await authClient.signIn.social({ provider: 'google', callbackURL: `${window.location.origin}${from}` })
    if (error) setError(error.message ?? 'Google sign-in is not available right now.')
  }

  return (
    <div className="grid min-h-dvh bg-canvas lg:grid-cols-2">
      <div className="relative hidden overflow-hidden bg-accent-gradient p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <Logo className="[&_span]:text-white" />
        <div>
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
            <span className="inline-flex items-center gap-2 rounded-full bg-white/20 px-3 py-1 text-xs font-medium">
              <Sparkles className="size-3.5" aria-hidden /> Evidence-backed product discovery
            </span>
            <h2 className="mt-6 text-4xl leading-tight font-semibold tracking-tight">From a pile of feedback to a roadmap you can defend.</h2>
            <p className="mt-4 max-w-md text-white/80">Every theme links back to the customer's own words, so every decision has a quote behind it.</p>
          </motion.div>
        </div>
        <p className="text-sm text-white/70">Interviews, tickets and surveys in. Prioritised themes, PRDs and a roadmap out.</p>
      </div>

      <div className="flex items-center justify-center p-6">
        <Card className="w-full max-w-md p-8">
          <Logo className="mb-6 lg:hidden" />
          {pendingEmail ? (
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">Check your email</h1>
              <p className="mt-1 text-sm text-muted">Enter the code we sent to {pendingEmail}.</p>
              <input aria-label="Verification code" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} placeholder="123456" className={`${field} mt-6 text-center tracking-[0.4em]`} />
              {error && <p role="alert" className="mt-3 text-sm text-negative">{error}</p>}
              <Button className="mt-4 w-full" loading={busy} disabled={code.trim().length < 4} onClick={verify}>Verify and continue</Button>
              <Button variant="ghost" className="mt-2 w-full" onClick={() => { setPendingEmail(null); setError(null) }}>Back</Button>
            </div>
          ) : (
            <form onSubmit={form.handleSubmit(submit)} noValidate>
              <h1 className="text-2xl font-semibold tracking-tight">{mode === 'signin' ? 'Welcome back' : 'Create your account'}</h1>
              <p className="mt-1 text-sm text-muted">{mode === 'signin' ? 'Sign in to your workspace.' : 'Start turning feedback into decisions.'}</p>
              <SegmentedControl label="Sign in or create an account" className="mt-6 w-full [&>button]:flex-1" value={mode} onChange={(m) => { setMode(m); setError(null) }} options={[{ value: 'signin', label: 'Sign in' }, { value: 'signup', label: 'Create account' }]} />

              <div className="mt-5 space-y-3">
                {mode === 'signup' && <input aria-label="Your name" autoComplete="name" placeholder="Your name" className={field} {...form.register('name')} />}
                <div>
                  <input aria-label="Email" type="email" autoComplete="email" placeholder="Email" className={field} {...form.register('email')} />
                  {form.formState.errors.email && <p role="alert" className="mt-1 px-2 text-xs text-negative">{form.formState.errors.email.message}</p>}
                </div>
                <div>
                  <input aria-label="Password" type="password" autoComplete={mode === 'signin' ? 'current-password' : 'new-password'} placeholder="Password" className={field} {...form.register('password')} />
                  {form.formState.errors.password && <p role="alert" className="mt-1 px-2 text-xs text-negative">{form.formState.errors.password.message}</p>}
                </div>
              </div>

              {error && <p role="alert" className="mt-3 text-sm text-negative">{error}</p>}
              <Button type="submit" className="mt-5 w-full" loading={busy}>{mode === 'signin' ? 'Sign in' : 'Create account'}</Button>
              <div className="my-4 flex items-center gap-3 text-xs text-muted"><span className="h-px flex-1 bg-line" />or<span className="h-px flex-1 bg-line" /></div>
              <Button type="button" variant="secondary" className="w-full" onClick={google}>Continue with Google</Button>
            </form>
          )}
        </Card>
      </div>
    </div>
  )
}
