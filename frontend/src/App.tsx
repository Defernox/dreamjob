import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import Candidatures from './pages/Candidatures'
import OffreDetail from './pages/OffreDetail'
import Offres from './pages/Offres'
import Profil from './pages/Profil'

export default function App() {
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
