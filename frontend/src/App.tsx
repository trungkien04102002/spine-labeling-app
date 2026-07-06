import { Route, Routes } from "react-router-dom";
import PatientList from "./pages/PatientList";
import Viewer from "./pages/Viewer";

function App() {
  return (
    <Routes>
      <Route path="/" element={<PatientList />} />
      <Route path="/viewer/:studyId" element={<Viewer />} />
    </Routes>
  );
}

export default App;
