import { Route, Routes } from "react-router-dom";
import Admin from "./pages/Admin";
import ModelVersions from "./pages/ModelVersions";
import PatientList from "./pages/PatientList";
import Viewer from "./pages/Viewer";

function App() {
  return (
    <Routes>
      <Route path="/" element={<PatientList />} />
      <Route path="/viewer/:studyId" element={<Viewer />} />
      <Route path="/models" element={<ModelVersions />} />
      <Route path="/admin" element={<Admin />} />
    </Routes>
  );
}

export default App;
