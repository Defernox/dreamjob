/** Le viseur de DreamJob — la même figure que l'icône du raccourci.
 *
 *  Trouver le bon poste, pas tous les postes : c'est ce que fait le score,
 *  et c'est ce que dit la marque. Redessinée en SVG plutôt que servie
 *  depuis le .ico, pour qu'elle prenne la couleur du texte qui l'entoure
 *  et reste nette à toutes les tailles.
 */
export function Marque({ taille = 22 }: { taille?: number }) {
  return (
    <svg
      width={taille}
      height={taille}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      className="shrink-0"
    >
      <circle cx="16" cy="16" r="13" stroke="currentColor" strokeWidth="2.5" opacity="0.35" />
      <circle cx="16" cy="16" r="7.5" stroke="currentColor" strokeWidth="2.5" opacity="0.7" />
      <circle cx="16" cy="16" r="2.75" className="fill-ambre-500" />
    </svg>
  )
}
