import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { LangProvider } from './lib/i18n'
import { RoomProvider } from './lib/room'
import './lib/strings.vi'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <LangProvider>
        <RoomProvider>
          <App />
        </RoomProvider>
      </LangProvider>
    </BrowserRouter>
  </StrictMode>,
)
