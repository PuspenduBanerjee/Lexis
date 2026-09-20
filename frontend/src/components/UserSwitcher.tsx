import { SEEDED_USERS, useUser } from "../state/UserContext";

export function UserSwitcher() {
  const { user, isGoogleAuthenticated, selectedDevUserId, setUserId } = useUser();

  // Once a real Google identity is authenticating requests (see
  // lexis_api/deps.get_current_user), the dev "Acting as" switcher has no effect
  // server-side - showing it would just be a lie about who's making requests.
  if (isGoogleAuthenticated) {
    return (
      <span className="row">
        <span className="muted">Signed in as</span>
        <strong>{user.username}</strong>
        <span className="muted">({user.role})</span>
      </span>
    );
  }

  return (
    <label className="row">
      <span className="muted">Acting as</span>
      <select value={selectedDevUserId} onChange={(e) => setUserId(Number(e.target.value))}>
        {SEEDED_USERS.map((u) => (
          <option key={u.id} value={u.id}>
            {u.username} ({u.role})
          </option>
        ))}
      </select>
    </label>
  );
}
