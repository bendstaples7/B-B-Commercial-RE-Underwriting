import { Navigate } from 'react-router-dom'

/** Legacy route — Open Letter setup lives on Direct Mail → Setup tab. */
export function OpenLetterImportArea() {
  return <Navigate to="/marketing/direct-mail?tab=setup" replace />
}
