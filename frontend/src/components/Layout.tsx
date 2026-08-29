import { NavLink, Outlet } from 'react-router-dom'
import { useStatistiques } from '../api/offres'
import { BandeauSante } from './BandeauSante'

const onglets = [
  { to: '/offres', libelle: 'Offres' },
  { to: '/candidatures', libelle: 'Candidatures' },
  { to: '/profil', libelle: 'Profil' },
]

export function Layout() {
  const { data: stats } = useStatistiques()
  const nouvelles = stats?.nouvelles ?? 0

  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-white border-b border-slate-200">
        <div className="px-6 h-14 flex items-center gap-8">
          <span className="font-semibold text-lg tracking-tight">DreamJob</span>
          <nav className="flex gap-1">
            {onglets.map((o) => (
              <NavLink
                key={o.to}
                to={o.to}
                className={({ isActive }) =>
                  `px-3 py-1.5 rounded-md text-sm font-medium transition-colors flex items-center gap-2 ${
                    isActive ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100'
                  }`
                }
              >
                {o.libelle}
                {/* Le badge ne vit que sur Offres, et disparaît une fois les
                    offres consultées : consulter une offre la marque comme vue. */}
                {o.to === '/offres' && nouvelles > 0 && (
                  <span
                    className="px-1.5 py-0.5 rounded-full bg-emerald-500 text-white text-xs
                               font-semibold tabular-nums leading-none"
                    title={`${nouvelles} offre(s) que vous n'avez pas encore ouverte(s)`}
                  >
                    {nouvelles > 99 ? '99+' : nouvelles}
                  </span>
                )}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <BandeauSante />
      <main className="flex-1 px-6 py-6">
        <Outlet />
      </main>
    </div>
  )
}
