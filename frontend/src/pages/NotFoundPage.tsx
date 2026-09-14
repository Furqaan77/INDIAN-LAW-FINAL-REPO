import { Link } from "react-router-dom";
import { StatePanel } from "../components/primitives";

export function NotFoundPage() {
  return (
    <div className="px-5">
      <StatePanel
        title="This page doesn’t exist"
        action={
          <Link to="/" className="rounded-md bg-ink px-4 py-2 text-sm text-paper hover:bg-ink-2">
            Start new research
          </Link>
        }
      >
        The link may be out of date. Research history lives on this device, so entries from another browser won’t open here.
      </StatePanel>
    </div>
  );
}
