import { useEffect, useState, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import AdminHub from "./pages/AdminHub";
import Join from "./pages/Join";
import PatientList from "./pages/PatientList";
import Survey from "./pages/Survey";
import Viewer from "./pages/Viewer";
import { enterByCode } from "./lib/api";
import { useRoom } from "./lib/room";

/**
 * Clinician pages open only inside a room; without one, the door.
 *
 * A personal link (/?phong=<code>) wins over whatever room this browser
 * remembers: the operator sent that link to put this person in that room, and
 * a shared computer may still hold the previous clinician's.
 */
function NeedsRoom({ children }: { children: ReactNode }) {
  const { room, enter } = useRoom();
  const code = new URLSearchParams(window.location.search).get("phong");
  const [linkError, setLinkError] = useState<string | null>(null);

  useEffect(() => {
    if (!code) return;
    enterByCode(code)
      .then((r) => {
        enter({ id: r.id, name: r.name });
        // Drop the code from the address bar, so a reload or a bookmark does
        // not keep re-entering by link.
        const url = new URL(window.location.href);
        url.searchParams.delete("phong");
        window.history.replaceState(null, "", url.pathname + url.search);
      })
      .catch(() => setLinkError(code));
  }, [code, enter]);

  if (code && !linkError) return null; // resolving the link
  if (!room) return <Join linkError={linkError} />;
  return <>{children}</>;
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
