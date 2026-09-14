// Deliberately renders with no dependency on useUser()/any API call - this page
// needs to be readable without being signed in (see the footer link in App.tsx and
// the README's "Before you expose it" section on Google OAuth consent screen
// requirements: Google's verifier checks this URL without a session).
const LAST_UPDATED = "2026-09-13";

export function PrivacyPolicyPage() {
  return (
    <div className="stack legal-page">
      <h2>Privacy Policy</h2>
      <p className="muted">Last updated: {LAST_UPDATED}</p>

      <p>
        Lexis is a semantic-layer tool: you author data models in Ossie YAML, and Lexis
        transpiles them into warehouse-native SQL and BI/AI-consumer formats, and can run
        queries against a connected data source. This page explains what a deployment of
        Lexis collects about you and what it does with it.
      </p>

      <h3>Who this applies to</h3>
      <p>
        This policy covers the specific instance of Lexis you're using (this URL), operated
        independently by whoever deployed it - not a hosted product run by the Lexis project
        itself. If you were given access to this instance, the operator is the person or team
        who invited you.
      </p>

      <h3>What's collected when you sign in</h3>
      <p>
        Sign-in is Google-based, handled entirely by a reverse proxy/tunnel in front of this
        app (not by Lexis itself) - your Google credentials are never seen by this
        application. Once Google authenticates you, the proxy forwards your <strong>account
        email address</strong> (and sometimes a display name) to the app, which uses it only
        to identify you and to look up or create your account record (email, a display name,
        and a role such as viewer/editor/admin). No other Google account data - contacts,
        files, calendar, etc. - is requested or accessible to this app.
      </p>
      <p>
        A local-development/demo build of Lexis may instead use a simple "Acting as" user
        switcher with no real identity or Google sign-in involved at all.
      </p>

      <h3>What's stored</h3>
      <ul>
        <li>Your account record: email, display name, and role.</li>
        <li>
          Semantic models you or others create: the Ossie YAML you author (dataset/metric/
          relationship definitions), plus which account owns each one.
        </li>
        <li>
          Data-source connections you or others configure: a name, type, and connection
          details (e.g. a file path, or a Snowflake account/user). Passwords are never stored -
          only the <em>name</em> of an environment variable the server reads at connect time.
        </li>
        <li>
          A database file you upload to test a metric (the "Run" tab's upload mode) is written
          to a temporary file for that one request only and deleted immediately afterward -
          it is never kept.
        </li>
      </ul>

      <h3>What's logged</h3>
      <p>
        The server writes one line per request to its own operational log (method, path,
        response status, and the identity header from the sign-in proxy, if any). This log
        exists for debugging and is not shared with anyone outside the operator.
      </p>

      <h3>Cookies and browser storage</h3>
      <p>
        Lexis itself sets no cookies. The web app stores one small, non-identifying value in
        your browser's local storage (which demo user the "Acting as" switcher last picked) -
        purely a UI convenience, never sent anywhere except back to this app. Whatever
        sign-in proxy sits in front of the app (Google-based, see above) may set its own
        cookies to keep you signed in; that's governed by that proxy provider's own policy,
        not this one.
      </p>

      <h3>Sharing</h3>
      <p>
        Nothing collected here is sold, shared with advertisers, or used for anything beyond
        operating this instance of Lexis for its invited users.
      </p>

      <h3>Data deletion</h3>
      <p>
        To have your account or data removed, contact the operator of this instance.
      </p>

      <h3>Changes</h3>
      <p>
        This page may be updated as the app changes; the "Last updated" date above reflects
        the most recent revision.
      </p>
    </div>
  );
}
