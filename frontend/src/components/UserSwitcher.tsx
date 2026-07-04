import { SEEDED_USERS, useUser } from "../state/UserContext";

export function UserSwitcher() {
  const { user, setUserId } = useUser();

  return (
    <label className="row">
      <span className="muted">Acting as</span>
      <select value={user.id} onChange={(e) => setUserId(Number(e.target.value))}>
        {SEEDED_USERS.map((u) => (
          <option key={u.id} value={u.id}>
            {u.username} ({u.role})
          </option>
        ))}
      </select>
    </label>
  );
}
