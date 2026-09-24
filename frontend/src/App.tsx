import { Navigate, Route, Routes } from 'react-router-dom'
import { useEtatAcces } from './api/acces'
import { Layout } from './components/Layout'
import Candidatures from './pages/Candidatures'
import Connexion from './pages/Connexion'
import OffreDetail from './pages/OffreDetail'
import Offres from './pages/Offres'
import Profil from './pages/Profil'

export default function App() {
  const { data: acces, isLoading } = useEtatAcces()
  // En local, `connecte` est toujours vrai : l'application s'affiche directement.
  if (isLoading) return null
  if (acces && !acces.connecte) return <Connexion />

  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Navigate to="/offres" replace />} />
        <Route path="offres" element={<Offres />} />
        <Route path="offres/:id" element={<OffreDetail />} />
        <Route path="candidatures" element={<Candidatures />} />
        <Route path="profil" element={<Profil />} />
        <Route path="*" element={<Navigate to="/offres" replace />} />
      </Route>
    </Routes>
  )
}
