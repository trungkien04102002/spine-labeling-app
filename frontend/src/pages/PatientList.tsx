import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getHealth } from "../lib/api";

type BackendStatus =
  | { state: "loading" }
  | { state: "ok"; status: string }
  | { state: "error"; message: string };

export default function PatientList() {
  const [backend, setBackend] = useState<BackendStatus>({ state: "loading" });

  useEffect(() => {
    let cancelled = false;

    getHealth()
      .then((res) => {
        if (!cancelled) setBackend({ state: "ok", status: res.status });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setBackend({
            state: "error",
            message: err instanceof Error ? err.message : String(err),
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <h1>Patients</h1>

      <p>
        {backend.state === "loading" && "Backend: checking..."}
        {backend.state === "ok" && `Backend: ${backend.status}`}
        {backend.state === "error" && `Backend: error (${backend.message})`}
      </p>

      <table border={1} cellPadding={8}>
        <thead>
          <tr>
            <th>Study ID</th>
            <th>Patient</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>demo</td>
            <td>Demo patient</td>
            <td>
              <Link to="/viewer/demo">Open</Link>
            </td>
          </tr>
        </tbody>
      </table>

      <p>upload coming soon</p>
    </div>
  );
}
