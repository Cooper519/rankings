import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'
import UniversityDrawer from '../components/UniversityDrawer'

interface DrawerCtx {
  open: (universityId: string) => void
  close: () => void
}
const Ctx = createContext<DrawerCtx>({ open: () => {}, close: () => {} })

export function useDrawer() {
  return useContext(Ctx)
}

export function DrawerProvider({ children }: { children: ReactNode }) {
  const [id, setId] = useState<string | null>(null)
  const open = useCallback((universityId: string) => setId(universityId), [])
  const close = useCallback(() => setId(null), [])
  return (
    <Ctx.Provider value={{ open, close }}>
      {children}
      <UniversityDrawer universityId={id} onClose={close} />
    </Ctx.Provider>
  )
}