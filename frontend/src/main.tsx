import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { CLE_ACCES } from './api/acces'
import { ErreurApi } from './api/client'
import App from './App'
import './index.css'

const nonConnecte = (erreur: unknown) => erreur instanceof ErreurApi && erreur.statut === 401

const client: QueryClient = new QueryClient({
  // Une session expirée en cours d'usage : toute requête répond 401. On relit
  // alors l'état d'accès, ce qui ramène à l'écran de connexion — sans cela,
  // l'application restait affichée avec des panneaux vides et des erreurs.
  queryCache: new QueryCache({
    onError: (erreur) => {
      if (nonConnecte(erreur)) client.invalidateQueries({ queryKey: CLE_ACCES })
    },
  }),
  defaultOptions: {
    queries: {
      // Retenter un 401 ne sert à rien : il faut se reconnecter.
      retry: (tentatives, erreur) => !nonConnecte(erreur) && tentatives < 1,
      refetchOnWindowFocus: false,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
