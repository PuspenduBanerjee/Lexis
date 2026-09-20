import type { ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { StaticRouter } from "react-router";
import { HomePage } from "../src/pages/HomePage";
import { PrivacyPolicyPage } from "../src/pages/PrivacyPolicyPage";
import { TermsOfServicePage } from "../src/pages/TermsOfServicePage";

// Prerender targets for scripts/prerender.mjs - each entry is a public,
// auth-free route whose content a non-JS crawler (e.g. Google's OAuth consent
// screen verifier) must be able to read straight out of the HTML response.
// Keep this list in sync with the "/", "/privacy", "/terms" routes in App.tsx.
export const ROUTES: Record<string, { title: string; Page: ComponentType }> = {
  "/": { title: "Lexis", Page: HomePage },
  "/privacy": { title: "Privacy Policy — Lexis", Page: PrivacyPolicyPage },
  "/terms": { title: "Terms of Service — Lexis", Page: TermsOfServicePage },
};

export function renderRoute(path: string): string {
  const { Page } = ROUTES[path];
  return renderToStaticMarkup(
    <StaticRouter location={path}>
      <Page />
    </StaticRouter>,
  );
}
