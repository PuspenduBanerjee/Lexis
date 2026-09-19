// Identifies who operates this specific deployment, for the Privacy Policy and
// Terms of Service pages - set via VITE_OPERATOR_LABEL / VITE_OPERATOR_CONTACT_URL
// at build time (see .env.production) so each self-hosted deployment names
// itself concretely instead of those pages reading as a generic, deployment-
// agnostic template (Google's OAuth consent screen review requires the policy
// be "clearly linked to your application and/or organization").
export const OPERATOR_LABEL: string =
  import.meta.env.VITE_OPERATOR_LABEL || "the operator of this instance";

export const OPERATOR_CONTACT_URL: string | undefined = import.meta.env.VITE_OPERATOR_CONTACT_URL;
