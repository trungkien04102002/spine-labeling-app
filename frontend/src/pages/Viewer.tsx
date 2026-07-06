import { Link, useParams } from "react-router-dom";

export default function Viewer() {
  const { studyId } = useParams<{ studyId: string }>();

  return (
    <div>
      <h1>Viewer — study {studyId}</h1>
      <p>
        <Link to="/">back to patients</Link>
      </p>
    </div>
  );
}
