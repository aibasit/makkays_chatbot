import { Link } from "react-router-dom";

export default function NotFoundPage() {
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-4 text-gray-700">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <Link to="/" className="text-blue-600 underline">
        Back to chat
      </Link>
    </div>
  );
}
