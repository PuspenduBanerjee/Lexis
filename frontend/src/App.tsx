import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { UserProvider } from "./state/UserContext";
import { UserSwitcher } from "./components/UserSwitcher";
import { ModelListPage } from "./pages/ModelListPage";
import { ModelDetailPage } from "./pages/ModelDetailPage";
import { ConnectionsPage } from "./pages/ConnectionsPage";
import { PrivacyPolicyPage } from "./pages/PrivacyPolicyPage";
import { TermsOfServicePage } from "./pages/TermsOfServicePage";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <UserProvider>
        <BrowserRouter>
          <header className="app-header">
            <div className="app-header-inner page-container">
              <div className="row">
                <h1>Lexis</h1>
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
              <Route path="/privacy" element={<PrivacyPolicyPage />} />
              <Route path="/terms" element={<TermsOfServicePage />} />
            </Routes>
          </main>
          <footer className="app-footer">
            <div className="page-container row">
              <Link to="/privacy">Privacy Policy</Link>
              <Link to="/terms">Terms of Service</Link>
            </div>
          </footer>
        </BrowserRouter>
      </UserProvider>
    </QueryClientProvider>
  );
}
