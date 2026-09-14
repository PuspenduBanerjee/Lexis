// See PrivacyPolicyPage.tsx's comment - same "readable while signed out" requirement.
const LAST_UPDATED = "2026-09-13";

export function TermsOfServicePage() {
  return (
    <div className="stack legal-page">
      <h2>Terms of Service</h2>
      <p className="muted">Last updated: {LAST_UPDATED}</p>

      <p>
        These terms govern your use of this deployment of Lexis, a semantic-layer tool for
        authoring data models and running queries against a connected data source. By using
        it, you agree to the terms below.
      </p>

      <h3>Provided as-is</h3>
      <p>
        The Service is provided <strong>"AS IS" and "AS AVAILABLE," without warranty of any
        kind, express or implied</strong>, including without limitation any warranty of
        merchantability, fitness for a particular purpose, non-infringement, accuracy, or
        that the Service will be uninterrupted, secure, error-free, or produce correct query
        results. You use it entirely at your own risk.
      </p>

      <h3>No liability</h3>
      <p>
        To the maximum extent permitted by applicable law, the operator of this Service and
        its contributors accept <strong>zero responsibility and no liability whatsoever</strong>{" "}
        for any direct, indirect, incidental, special, consequential, or exemplary damages -
        including loss of data, loss of profits, business interruption, or reliance on any
        metric, query result, or transpiled output produced by the Service - arising out of
        or in connection with your use of, or inability to use, the Service, however caused
        and under any theory of liability, even if advised of the possibility of such
        damages.
      </p>

      <h3>Your responsibility</h3>
      <ul>
        <li>
          You are responsible for whatever data you connect, upload, or model in the Service,
          and for verifying any result before relying on it for a real decision.
        </li>
        <li>You are responsible for keeping any data-source credentials you configure secure.</li>
        <li>You must not use the Service for anything unlawful or for data you're not authorized to access.</li>
      </ul>

      <h3>No SLA, availability, or continuity guarantee</h3>
      <p>
        The operator may modify, suspend, restrict access to, or discontinue the Service, in
        whole or in part, at any time, without notice and without liability for doing so.
        Data you've stored (models, connections, accounts) may be lost, reset, or become
        unavailable; keep your own copies of anything you can't afford to lose.
      </p>

      <h3>Changes to these terms</h3>
      <p>
        These terms may be updated as the app changes; continued use after an update means
        you accept the revised terms. The "Last updated" date above reflects the most recent
        revision.
      </p>

      <p className="muted">
        This is a template for an independently operated, small-scale deployment of an
        open-source tool - not legal advice, and not reviewed by an attorney. If this
        instance serves paying customers or handles data with real regulatory exposure, have
        counsel review it.
      </p>
    </div>
  );
}
