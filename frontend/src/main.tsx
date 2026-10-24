import '@fontsource-variable/geist'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { toast } from 'sonner'
import App from './App.tsx'
import './index.css'
import { ApiError } from './lib/errors'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      // A 4xx will not get better by asking again; a 5xx or a dropped connection might.
      retry: (failures, error) => !(error instanceof ApiError && error.status < 500) && failures < 2,
    },
    mutations: {
      onError: (error) => toast.error(error instanceof Error ? error.message : 'Something went wrong. Please try again.'),
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
