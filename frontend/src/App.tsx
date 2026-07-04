import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { UserProvider } from "./state/UserContext";
import { UserSwitcher } from "./components/UserSwitcher";
import { ModelListPage } from "./pages/ModelListPage";
import { ModelDetailPage } from "./pages/ModelDetailPage";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <UserProvider>
        <BrowserRouter>
          <header className="app-header">
            <h1>Semantica</h1>
            <UserSwitcher />
          </header>
          <main className="app-main">
            <Routes>
              <Route path="/" element={<ModelListPage />} />
              <Route path="/models/:id" element={<ModelDetailPage />} />
            </Routes>
          </main>
        </BrowserRouter>
      </UserProvider>
    </QueryClientProvider>
  );
}
