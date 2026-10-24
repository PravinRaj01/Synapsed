import { Check, FlaskConical, Plus, Trash2, Upload } from 'lucide-react'
import { useState } from 'react'
import { useFieldArray, useForm } from 'react-hook-form'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { Field, inputClass } from '@/components/ui/Field'
import { cn } from '@/lib/cn'
import { DEFAULT_SEGMENTS, EMPTY_SETUP, MAX_SEGMENTS, setupSchema, TIERS, type SetupValues } from '@/lib/onboarding'
import { useCreateSetup, useWorkspaces } from '@/lib/workspaces'
import { zodResolver } from '@/lib/zodResolver'
import { Loading, Skeleton } from '@/components/ui/Skeleton'

type Step = 'business' | 'campaign' | 'data'

const STEP_FIELDS: Record<Exclude<Step, 'data'>, Parameters<ReturnType<typeof useForm<SetupValues>>['trigger']>[0]> = {
  business: ['profile.company', 'profile.industry', 'profile.domain', 'profile.targetAudience', 'profile.ownerRole'],
  campaign: ['campaign.name', 'campaign.goal', 'campaign.segments'],
}

const STEP_TITLES: Record<Step, string> = { business: 'Your business', campaign: 'Your campaign', data: 'Your data' }

function Stepper({ steps, current }: { steps: Step[]; current: Step }) {
  const at = steps.indexOf(current)
  return (
    <ol className="mb-6 flex items-center gap-2" aria-label="Progress">
      {steps.map((s, i) => (
        <li key={s} className="flex items-center gap-2" aria-current={s === current ? 'step' : undefined}>
          <span
            className={cn(
              'grid size-7 place-items-center rounded-full text-xs font-semibold',
              i < at ? 'bg-accent text-white' : s === current ? 'bg-ink text-ink-contrast' : 'bg-inner text-muted',
            )}
          >
            {i < at ? <Check className="size-4" aria-hidden /> : i + 1}
          </span>
          <span className={cn('text-sm', s === current ? 'font-medium text-ink' : 'text-muted')}>{STEP_TITLES[s]}</span>
          {i < steps.length - 1 && <span className="mx-1 h-px w-6 bg-line" aria-hidden />}
        </li>
      ))}
    </ol>
  )
}

export default function Onboarding() {
  const navigate = useNavigate()
  const { data: workspaces = [], isLoading } = useWorkspaces()
  const workspace = workspaces[0] ?? null
  const needsProfile = !isLoading && !workspace
  const steps: Step[] = needsProfile ? ['business', 'campaign', 'data'] : ['campaign', 'data']
  const [step, setStep] = useState<Step | null>(null) // null = the first step, which is only known once the workspaces have loaded
  const create = useCreateSetup()

  const form = useForm<SetupValues>({
    resolver: (values, context, options) => zodResolver(setupSchema(needsProfile))(values, context, options),
    defaultValues: EMPTY_SETUP,
  })
  const { register, control, formState, trigger, handleSubmit } = form
  const segments = useFieldArray({ control, name: 'campaign.segments' })
  const errors = formState.errors

  const current: Step = step && steps.includes(step) ? step : steps[0]

  async function next() {
    if (current === 'data') return
    if (await trigger(STEP_FIELDS[current])) setStep(steps[steps.indexOf(current) + 1])
  }

  const submit = (withDemo: boolean) =>
    handleSubmit(async (values) => {
      try {
        const result = await create.mutateAsync({ values, workspaceId: workspace?.id ?? null, withDemo })
        if (result.demoError) toast.error(`Your campaign is ready, but the demo did not load: ${result.demoError}`)
        else if (result.demoLoaded) toast.success('Demo sandbox loaded. Have a look around.')
        navigate(withDemo ? '/dashboard' : '/vault', { replace: true })
      } catch (e) {
        toast.error(e instanceof Error ? e.message : 'Something went wrong. Please try again.')
      }
    })()

  return (
    <>
      <PageHeader
        title={workspace ? 'New campaign' : 'Welcome to Synapsed'}
        subtitle={workspace ? 'A campaign groups the sources for one research question.' : 'Tell us a little about your product so we can set up your first campaign.'}
      />
      <Card className="mx-auto max-w-2xl p-6 sm:p-8">
        <Stepper steps={steps} current={current} />

        {isLoading && (
          <Loading label="Loading" className="space-y-4">
            <Skeleton className="h-11 w-full rounded-full" />
            <Skeleton className="h-11 w-full rounded-full" />
            <Skeleton className="h-11 w-2/3 rounded-full" />
          </Loading>
        )}

        {!isLoading && current === 'business' && (
          <section className="space-y-4" aria-label="Your business">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Company" error={errors.profile?.company?.message}>
                <input className={inputClass} autoComplete="organization" placeholder="Acme Inc." {...register('profile.company')} />
              </Field>
              <Field label="Industry" error={errors.profile?.industry?.message}>
                <input className={inputClass} placeholder="B2B software" {...register('profile.industry')} />
              </Field>
            </div>
            <Field label="What does your product do?" hint="One sentence is plenty." error={errors.profile?.domain?.message}>
              <input className={inputClass} placeholder="Invoicing and expenses for finance teams" {...register('profile.domain')} />
            </Field>
            <Field label="Who is it for?" error={errors.profile?.targetAudience?.message}>
              <input className={inputClass} placeholder="Finance managers at growing companies" {...register('profile.targetAudience')} />
            </Field>
            <Field label="Your role" error={errors.profile?.ownerRole?.message}>
              <input className={inputClass} placeholder="Head of Product" {...register('profile.ownerRole')} />
            </Field>
          </section>
        )}

        {!isLoading && current === 'campaign' && (
          <section className="space-y-5" aria-label="Your campaign">
            <Field label="Campaign name" error={errors.campaign?.name?.message}>
              <input className={inputClass} placeholder="Q4 churn research" {...register('campaign.name')} />
            </Field>
            <Field label="What do you want to learn?" hint="Optional. It keeps the research focused." error={errors.campaign?.goal?.message}>
              <input className={inputClass} placeholder="Why do enterprise customers leave?" {...register('campaign.goal')} />
            </Field>

            <div>
              <h2 className="text-sm font-medium text-ink">Customer segments</h2>
              <p className="mt-0.5 mb-3 px-0 text-xs text-muted">
                A weight says how much a customer group counts when problems are ranked. A problem raised by an Enterprise customer (weight 3) counts three times as much as the same problem from a Free user (weight 1).
              </p>
              <ul className="space-y-2">
                {segments.fields.map((field, i) => (
                  <li key={field.id} className="grid grid-cols-[1fr_5.5rem_auto] gap-2 sm:grid-cols-[1fr_9rem_5.5rem_auto]">
                    <input aria-label={`Segment ${i + 1} name`} className={cn(inputClass, 'col-span-3 sm:col-span-1')} {...register(`campaign.segments.${i}.name`)} />
                    <select aria-label={`Segment ${i + 1} type`} className={inputClass} {...register(`campaign.segments.${i}.tier`)}>
                      {TIERS.map((t) => (
                        <option key={t.value} value={t.value}>
                          {t.label}
                        </option>
                      ))}
                    </select>
                    <input aria-label={`Segment ${i + 1} weight`} type="number" step="0.5" min="0.1" max="20" className={inputClass} {...register(`campaign.segments.${i}.weight`, { valueAsNumber: true })} />
                    <button
                      type="button"
                      onClick={() => segments.remove(i)}
                      aria-label={`Remove segment ${i + 1}`}
                      className="grid size-11 place-items-center rounded-full text-muted transition-colors hover:bg-inner hover:text-negative"
                    >
                      <Trash2 className="size-4" aria-hidden />
                    </button>
                    {errors.campaign?.segments?.[i] && (
                      <p role="alert" className="col-span-full px-2 text-xs text-negative">
                        {errors.campaign.segments[i]?.name?.message ?? errors.campaign.segments[i]?.weight?.message}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
              {errors.campaign?.segments?.message && (
                <p role="alert" className="mt-2 px-2 text-xs text-negative">
                  {errors.campaign.segments.message}
                </p>
              )}
              {errors.campaign?.segments?.root?.message && (
                <p role="alert" className="mt-2 px-2 text-xs text-negative">
                  {errors.campaign.segments.root.message}
                </p>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                <Button type="button" variant="secondary" size="sm" disabled={segments.fields.length >= MAX_SEGMENTS} onClick={() => segments.append({ name: '', tier: 'other', weight: 1 })}>
                  <Plus className="size-4" aria-hidden /> Add segment
                </Button>
                <Button type="button" variant="ghost" size="sm" onClick={() => segments.replace(DEFAULT_SEGMENTS)}>
                  Reset to defaults
                </Button>
              </div>
            </div>
          </section>
        )}

        {!isLoading && current === 'data' && (
          <section aria-label="Your data">
            <p className="mb-4 text-sm text-muted">How would you like to start?</p>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <button
                type="button"
                disabled={create.isPending}
                onClick={() => submit(true)}
                className="group rounded-card bg-accent-gradient p-6 text-left text-white shadow-card transition-transform hover:-translate-y-1 disabled:opacity-60"
              >
                <span className="grid size-10 place-items-center rounded-full bg-white/20">
                  <FlaskConical className="size-5" aria-hidden />
                </span>
                <span className="mt-4 block text-base font-semibold">Explore the demo sandbox</span>
                <span className="mt-1 block text-sm text-white/80">Ten invented interviews, tickets and surveys, already analysed. Nothing to upload.</span>
              </button>
              <button
                type="button"
                disabled={create.isPending}
                onClick={() => submit(false)}
                className="rounded-card border border-line bg-inner p-6 text-left transition-transform hover:-translate-y-1 disabled:opacity-60"
              >
                <span className="grid size-10 place-items-center rounded-full bg-accent-tint text-accent">
                  <Upload className="size-5" aria-hidden />
                </span>
                <span className="mt-4 block text-base font-semibold text-ink">Upload my own data</span>
                <span className="mt-1 block text-sm text-muted">Start with an empty campaign and add your sources in the Knowledge Vault.</span>
              </button>
            </div>
            {create.isPending && (
              <p role="status" className="mt-4 text-sm text-muted">
                Setting things up…
              </p>
            )}
          </section>
        )}

        {!isLoading && (
          <div className="mt-8 flex items-center justify-between">
            {steps.indexOf(current) > 0 ? (
              <Button type="button" variant="ghost" disabled={create.isPending} onClick={() => setStep(steps[steps.indexOf(current) - 1])}>
                Back
              </Button>
            ) : (
              <span />
            )}
            {current !== 'data' && (
              <Button type="button" onClick={next}>
                Continue
              </Button>
            )}
          </div>
        )}
      </Card>
    </>
  )
}
