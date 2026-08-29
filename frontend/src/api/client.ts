/** Client HTTP minimal vers l'API locale (relayée par Vite sur /api). */

export class ErreurApi extends Error {
  constructor(public statut: number, message: string) {
    super(message)
  }
}

async function requete<T>(url: string, options?: RequestInit): Promise<T> {
  const reponse = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!reponse.ok) {
    let detail = `${reponse.status} ${reponse.statusText}`
    try {
      const corps = await reponse.json()
      if (corps?.detail) detail = String(corps.detail)
    } catch {
      /* corps non JSON : on garde le statut brut */
    }
    throw new ErreurApi(reponse.status, detail)
  }
  return reponse.json() as Promise<T>
}

/** Envoi de fichier : pas de Content-Type, le navigateur pose la frontière multipart. */
async function envoiFichier<T>(url: string, donnees: FormData): Promise<T> {
  const reponse = await fetch(url, { method: 'POST', body: donnees })
  if (!reponse.ok) {
    let detail = `${reponse.status} ${reponse.statusText}`
    try {
      const corps = await reponse.json()
      if (corps?.detail) detail = String(corps.detail)
    } catch {
      /* corps non JSON */
    }
    throw new ErreurApi(reponse.status, detail)
  }
  return reponse.json() as Promise<T>
}

export const api = {
  get: <T>(url: string) => requete<T>(url),
  post: <T>(url: string, corps?: unknown) =>
    requete<T>(url, { method: 'POST', body: corps ? JSON.stringify(corps) : undefined }),
  put: <T>(url: string, corps: unknown) =>
    requete<T>(url, { method: 'PUT', body: JSON.stringify(corps) }),
  patch: <T>(url: string, corps: unknown) =>
    requete<T>(url, { method: 'PATCH', body: JSON.stringify(corps) }),
  delete: <T>(url: string) => requete<T>(url, { method: 'DELETE' }),
  upload: envoiFichier,
}
