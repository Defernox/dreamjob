import { useState } from 'react'
import { useReglages } from '../api/hooks'
import {
  useCreerRecherche,
  useMajRecherche,
  useRecherches,
  useSupprimerRecherche,
  type Recherche,
} from '../api/recherches'
import { Bouton } from './champs'
import { ChoixMultiple, ListeTags } from './ListeTags'

/** Gestion des recherches enregistrées.
 *
 *  Chaque recherche active est jouée à chaque scan, et leurs résultats sont
 *  dédupliqués ensemble : une offre trouvée deux fois n'est stockée qu'une fois.
 */
export function Recherches() {
  const { data: recherches } = useRecherches()
  const { data: reglages } = useReglages()
  const creer = useCreerRecherche()
  const maj = useMajRecherche()
  const supprimer = useSupprimerRecherche()

  const [nouveauNom, setNouveauNom] = useState('')
  const actives = (recherches ?? []).filter((r) => r.active).length

  const ajouter = () => {
    const nom = nouveauNom.trim()
    if (!nom) return
    creer.mutate({ nom, mots_cles: [] }, { onSuccess: () => setNouveauNom('') })
  }

  return (
    <details className="bg-white rounded-lg border border-slate-200 px-4 py-3">
      <summary className="cursor-pointer select-none text-sm font-medium flex items-center gap-2">
        Recherches enregistrées
        <span className="text-slate-400 font-normal">
          {recherches?.length
            ? `${actives} active${actives > 1 ? 's' : ''} sur ${recherches.length}`
            : 'aucune — le profil sert de recherche par défaut'}
        </span>
      </summary>

      <p className="text-xs text-slate-500 mt-2 mb-3">
        Chaque recherche active est jouée à chaque scan, manuel comme automatique.
        Laisser les pays ou les contrats vides reprend ceux de votre profil.
      </p>

      <div className="space-y-3">
        {recherches?.map((r) => (
          <Ligne
            key={r.id}
            recherche={r}
            pays={reglages?.vocabulaires.pays ?? []}
            contrats={reglages?.vocabulaires.contrats ?? []}
            onChange={(champs) => maj.mutate({ id: r.id, ...champs })}
            onSupprimer={() => supprimer.mutate(r.id)}
          />
        ))}
      </div>

      <div className="flex gap-2 mt-3 pt-3 border-t border-slate-100">
        <input
          value={nouveauNom}
          onChange={(e) => setNouveauNom(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && ajouter()}
          placeholder="Nom d'une nouvelle recherche — ex. « V.I.E finance »"
          className="flex-1 rounded-md border border-slate-300 px-2.5 py-1.5 text-sm"
        />
        <Bouton onClick={ajouter} disabled={!nouveauNom.trim() || creer.isPending}>
          Ajouter
        </Bouton>
      </div>
      {creer.isError && (
        <p className="text-xs text-red-700 mt-2">{(creer.error as Error).message}</p>
      )}
    </details>
  )
}

function Ligne({ recherche, pays, contrats, onChange, onSupprimer }: {
  recherche: Recherche
  pays: string[]
  contrats: string[]
  onChange: (champs: Partial<Recherche>) => void
  onSupprimer: () => void
}) {
  const [ouverte, setOuverte] = useState(false)

  return (
    <div className={`rounded-md border p-3 ${
      recherche.active ? 'border-slate-200' : 'border-slate-200 bg-slate-50/60'
    }`}>
      <div className="flex items-center gap-3">
        <label className="flex items-center gap-2 text-sm" title="Jouer cette recherche">
          <input
            type="checkbox"
            checked={recherche.active}
            onChange={(e) => onChange({ active: e.target.checked })}
          />
          <span className={recherche.active ? 'font-medium' : 'text-slate-500'}>
            {recherche.nom}
          </span>
        </label>
        <span className="text-xs text-slate-400 truncate flex-1">
          {recherche.mots_cles.join(', ') || 'aucun mot-clé — toutes les offres'}
        </span>
        <button
          type="button"
          onClick={() => setOuverte(!ouverte)}
          className="text-xs text-slate-500 hover:text-slate-900"
        >
          {ouverte ? 'replier' : 'régler'}
        </button>
        <button
          type="button"
          onClick={onSupprimer}
          className="text-slate-400 hover:text-red-600"
          title="Supprimer cette recherche"
        >
          ×
        </button>
      </div>

      {ouverte && (
        <div className="mt-3 space-y-3 pt-3 border-t border-slate-100">
          <div>
            <span className="block text-xs font-medium text-slate-600 mb-1">Mots-clés</span>
            <ListeTags
              valeurs={recherche.mots_cles}
              onChange={(v) => onChange({ mots_cles: v })}
              placeholder="Tapez un mot-clé puis Entrée"
            />
          </div>
          <div>
            <span className="block text-xs font-medium text-slate-600 mb-1.5">
              Pays <span className="font-normal text-slate-400">— vide : ceux du profil</span>
            </span>
            <ChoixMultiple
              options={pays}
              valeurs={recherche.pays}
              onChange={(v) => onChange({ pays: v })}
            />
          </div>
          <div>
            <span className="block text-xs font-medium text-slate-600 mb-1.5">
              Contrats <span className="font-normal text-slate-400">— vide : ceux du profil</span>
            </span>
            <ChoixMultiple
              options={contrats}
              valeurs={recherche.contrats}
              onChange={(v) => onChange({ contrats: v })}
            />
          </div>
        </div>
      )}
    </div>
  )
}
