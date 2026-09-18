import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router-dom";
import { useWorkspaceWebMcpTools } from "./hooks/useWorkspaceWebMcpTools";
import { UserProvider } from "./state/UserContext";
import { UserSwitcher } from "./components/UserSwitcher";
import { ModelListPage } from "./pages/ModelListPage";
import { ModelDetailPage } from "./pages/ModelDetailPage";
import { ConnectionsPage } from "./pages/ConnectionsPage";
import { HomePage } from "./pages/HomePage";
import { PrivacyPolicyPage } from "./pages/PrivacyPolicyPage";
import { TermsOfServicePage } from "./pages/TermsOfServicePage";

const queryClient = new QueryClient();

export default function App() {
  // Registered once for the app's lifetime - workspace-wide list_models /
  // list_connections / list_metrics / query_metric tools (see the hook's doc
  // comment). Per-model query_<metric> tools are registered separately by
  // ModelDetailPage, scoped to that page's mount lifetime.
  useWorkspaceWebMcpTools();

  return (
    <QueryClientProvider client={queryClient}>
      <UserProvider>
        <BrowserRouter>
          <header className="app-header">
            <div className="app-header-inner page-container">
              <div className="row">
                <Link to="/" className="brand-link">
                  <h1>Lexis</h1>
                </Link>
                <nav className="row">
                  <Link to="/models">Models</Link>
                  <Link to="/connections">Connections</Link>
                </nav>
              </div>
              <UserSwitcher />
            </div>
          </header>
          <main className="app-main page-container">
            <Routes>
              <Route path="/" element={<HomePage />} />
              <Route path="/models" element={<ModelListPage />} />
              <Route path="/models/:id" element={<ModelDetailPage />} />
              <Route path="/connections" element={<ConnectionsPage />} />
              {/* Kept as a redirect for anyone who bookmarked or configured the
                  earlier /home URL (e.g. as a Google OAuth consent screen field or
                  a Cloudflare Access bypass path) - the homepage now lives at "/". */}
              <Route path="/home" element={<Navigate to="/" replace />} />
              <Route path="/privacy" element={<PrivacyPolicyPage />} />
              <Route path="/terms" element={<TermsOfServicePage />} />
            </Routes>
          </main>
          <footer className="app-footer">
            <div className="page-container row">
              <Link to="/">Home</Link>
              <Link to="/privacy">Privacy Policy</Link>
              <Link to="/terms">Terms of Service</Link>
            </div>
          </footer>
        </BrowserRouter>
      </UserProvider>
    </QueryClientProvider>
  );
}
