import { Link } from "react-router-dom";

// Deliberately renders with no dependency on useUser()/any API call, same as
// PrivacyPolicyPage/TermsOfServicePage - this is the app's "/" route and the page a
// Google OAuth consent screen's "Application home page" field should point at, since
// it needs to explain the app's purpose and be reachable without signing in. See the
// README's "Before you expose it" section for carving out a Cloudflare Access bypass
// so it actually is reachable unauthenticated in production.
export function HomePage() {
  return (
    <div className="stack legal-page">
      <h2>Lexis</h2>
      <p>
        Lexis is an open, <a href="https://github.com/apache/ossie">Apache Ossie</a>-native
        semantic layer: author a data model once in Ossie YAML, then transpile it to
        warehouse-native SQL (Snowflake, BigQuery, Databricks, DuckDB, Postgres) and to
        formats BI/AI consumers understand (Cube.js schema, dbt-core Ossie documents, MCP
        tool manifests for AI agents).
      </p>

      <h3>What you can do here</h3>
      <ul>
        <li>Design semantic models - datasets, fields, relationships, and metrics - in a graphical editor or by pasting Ossie YAML directly.</li>
        <li>Transpile a model to any supported target and preview the generated output.</li>
        <li>Run a metric live against a demo dataset, an uploaded DuckDB file, or a configured Snowflake/DuckDB connection.</li>
        <li>Serve a model as a live MCP server, so an AI assistant can query its metrics with real results.</li>
      </ul>

      <h3>Access</h3>
      <p>
        This instance is operated independently for its own invited users, not offered as a
        public product - see the <Link to="/privacy">Privacy Policy</Link> for who that is.
        Signing in uses your Google account; if you haven't been given access, contact the
        person who invited you.
      </p>
      <p>
        <Link to="/models">Open the app →</Link>
      </p>

      <h3>Learn more</h3>
      <p>
        <a href="https://github.com/PuspenduBanerjee/Lexis">Source code</a> ·{" "}
        <Link to="/privacy">Privacy Policy</Link> · <Link to="/terms">Terms of Service</Link>
      </p>
    </div>
  );
}
