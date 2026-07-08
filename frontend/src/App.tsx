import { Route, Routes } from "react-router-dom";

import ChatPage from "./routes/ChatPage";
import NotFoundPage from "./routes/NotFoundPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<ChatPage />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
