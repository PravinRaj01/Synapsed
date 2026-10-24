import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { authClient, clearAccessToken } from './auth'

export type SessionUser = { id: string; name: string; email: string; image?: string | null }

/** The signed-in user, or null. Cached for a few minutes; the session cookie is the source of truth. */
export function useSession() {
  return useQuery({
    queryKey: ['session'],
    queryFn: async (): Promise<SessionUser | null> => {
      const { data } = await authClient.getSession()
      const user = data?.user
      return user ? { id: user.id, name: user.name, email: user.email, image: user.image } : null
    },
    staleTime: 5 * 60_000,
    retry: false,
  })
}

export function useSignOut() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  return useMutation({
    mutationFn: () => authClient.signOut(),
    onSettled: () => {
      clearAccessToken()
      queryClient.clear() // nothing from this user may linger for the next one
      navigate('/login', { replace: true })
    },
  })
}

/** The words of the user's name; with no name, the words of the part of the email before the @. */
function nameWords(user: Pick<SessionUser, 'name' | 'email'>): string[] {
  const source = user.name?.trim() || user.email.split('@')[0]
  return source.split(/[\s._-]+/).filter(Boolean)
}

/** "Maya Tan" -> "MT", "maya.tan@x.io" -> "MT", "solo@x.io" -> "S". */
export function initials(user: Pick<SessionUser, 'name' | 'email'>): string {
  const words = nameWords(user)
  return ((words[0]?.[0] ?? '?') + (words.length > 1 ? words[1][0] : '')).toUpperCase()
}

/** The first word of the user's name, for "Good morning, Maya". */
export function firstName(user: Pick<SessionUser, 'name' | 'email'>): string {
  return nameWords(user)[0] ?? 'there'
}
