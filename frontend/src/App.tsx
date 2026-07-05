import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { UserProvider } from "./state/UserContext";
import { UserSwitcher } from "./components/UserSwitcher";
import { ModelListPage } from "./pages/ModelListPage";
import { ModelDetailPage } from "./pages/ModelDetailPage";
import { ConnectionsPage } from "./pages/ConnectionsPage";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <UserProvider>
        <BrowserRouter>
          <header className="app-header">
            <div className="app-header-inner page-container">
              <div className="row">
                <h1>Semantica</h1>
                <nav className="row">
                  <Link to="/">Models</Link>
                  <Link to="/connections">Connections</Link>
                </nav>
              </div>
              <UserSwitcher />
            </div>
          </header>
          <main className="app-main page-container">
            <Routes>
              <Route path="/" element={<ModelListPage />} />
              <Route path="/models/:id" element={<ModelDetailPage />} />
              <Route path="/connections" element={<ConnectionsPage />} />
            </Routes>
          </main>
        </BrowserRouter>
      </UserProvider>
    </QueryClientProvider>
  );
}
