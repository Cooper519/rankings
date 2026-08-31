import { HashRouter, Routes, Route } from 'react-router-dom'
import { motion, useScroll, useSpring } from 'framer-motion'
import Nav from './components/Nav'
import CanvasField from './components/CanvasField'
import Home from './pages/Home'
import Ranking from './pages/Ranking'
import Programs from './pages/Programs'
import Me from './pages/Me'
import University from './pages/University'
import Compare from './pages/Compare'
import DataStatus from './pages/DataStatus'
import { DrawerProvider } from './store/drawer'

function ScrollProgress() {
  const { scrollYProgress } = useScroll()
  const scaleX = useSpring(scrollYProgress, { stiffness: 120, damping: 30, mass: 0.4 })
  return <motion.div className="scroll-prog" style={{ scaleX }} aria-hidden />
}

export default function App() {
  return (
    <HashRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <CanvasField />
      <div className="grain" aria-hidden />
      <ScrollProgress />
      <div className="app-root">
        <Nav />
        <DrawerProvider>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/ranking" element={<Ranking />} />
            <Route path="/programs" element={<Programs />} />
            <Route path="/university/:id" element={<University />} />
            <Route path="/compare" element={<Compare />} />
            <Route path="/me" element={<Me />} />
            <Route path="/data-status" element={<DataStatus />} />
            <Route path="*" element={<Home />} />
          </Routes>
        </DrawerProvider>
      </div>
    </HashRouter>
  )
}
