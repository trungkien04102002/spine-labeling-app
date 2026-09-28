import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import AdminHub from "./pages/AdminHub";
import Join from "./pages/Join";
import PatientList from "./pages/PatientList";
import Survey from "./pages/Survey";
import Viewer from "./pages/Viewer";
import { useRoom } from "./lib/room";

/** Clinician pages open only inside a room; without one, the door. */
function NeedsRoom({ children }: { children: ReactNode }) {
  const { room } = useRoom();
  return room ? <>{children}</> : <Join />;
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<NeedsRoom><PatientList /></NeedsRoom>} />
      <Route path="/viewer/:studyId" element={<NeedsRoom><Viewer /></NeedsRoom>} />
      <Route path="/survey" element={<NeedsRoom><Survey /></NeedsRoom>} />
      {/* Everything an operator uses, behind one passphrase. */}
      <Route path="/admin/*" element={<AdminHub />} />
      {/* The old top-level page, kept as a redirect so old links still work
          -- but through the lock, not around it. */}
      <Route path="/models" element={<Navigate to="/admin/models" replace />} />
    </Routes>
  );
}

export default App;
