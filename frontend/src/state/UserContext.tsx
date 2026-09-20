import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../api/client";
import { setCurrentUserId } from "../api/client";
import type { Role, UserOut } from "../api/types";

export interface DemoUser {
  id: number;
  username: string;
  role: Role;
}

// The 3 users seeded by lexis_api/seed.py - only used to drive the dev-only "Acting
// as" switcher (see UserSwitcher). A real Google-authenticated identity (see
// lexis_api/deps.py) isn't in this list; it comes back from `/api/users/me` instead
// and always wins over whatever's selected here (see isGoogleAuthenticated below).
export const SEEDED_USERS: DemoUser[] = [
  { id: 1, username: "admin", role: "admin" },
  { id: 2, username: "editor1", role: "editor" },
  { id: 3, username: "viewer1", role: "viewer" },
];

const STORAGE_KEY = "lexis.currentUserId";

interface UserContextValue {
  /** The backend's actual resolved identity for the current request headers -
   * not necessarily the dev switcher's selection (Google auth, when present,
   * always wins server-side; see deps.get_current_user). */
  user: UserOut;
  /** True once `/api/users/me` has replied at least once (real Google auth or the
   * dev stub), so callers can avoid a flash of the wrong identity on first load. */
  ready: boolean;
  /** True when `user` is a real signed-in Google identity rather than the dev
   * stub - i.e. the "Acting as" switcher no longer has any effect. */
  isGoogleAuthenticated: boolean;
  /** The dev switcher's current pick. Only takes effect when the backend isn't
   * already authenticating the request via Google (see isGoogleAuthenticated). */
  selectedDevUserId: number;
  setUserId: (id: number) => void;
}

const UserContext = createContext<UserContextValue | null>(null);

function devFallbackUser(id: number): UserOut {
  const demo = SEEDED_USERS.find((u) => u.id === id) ?? SEEDED_USERS[0];
  return { ...demo, email: null };
}

export function UserProvider({ children }: { children: ReactNode }) {
  const [selectedDevUserId, setSelectedDevUserId] = useState<number>(() => {
    const stored = Number(localStorage.getItem(STORAGE_KEY));
    return SEEDED_USERS.some((u) => u.id === stored) ? stored : SEEDED_USERS[0].id;
  });
  const [user, setUser] = useState<UserOut>(() => devFallbackUser(selectedDevUserId));
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setCurrentUserId(selectedDevUserId);
    localStorage.setItem(STORAGE_KEY, String(selectedDevUserId));

    let cancelled = false;
    api
      .me()
      .then((me) => {
        if (!cancelled) setUser(me);
      })
      .catch(() => {
        // No usable identity at all (e.g. the dev stub was disabled server-side -
        // LEXIS_DEV_AUTH_HEADER_ENABLED=0 - and there's no Google header either).
        // Fall back to the switcher's pick so the UI still renders something
        // rather than getting stuck with no user, even though every real API call
        // will then 401.
        if (!cancelled) setUser(devFallbackUser(selectedDevUserId));
      })
      .finally(() => {
        if (!cancelled) setReady(true);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedDevUserId]);

  const value = useMemo<UserContextValue>(
    () => ({
      user,
      ready,
      isGoogleAuthenticated: user.email != null,
      selectedDevUserId,
      setUserId: setSelectedDevUserId,
    }),
    [user, ready, selectedDevUserId],
  );

  return <UserContext.Provider value={value}>{children}</UserContext.Provider>;
}

export function useUser(): UserContextValue {
  const ctx = useContext(UserContext);
  if (!ctx) throw new Error("useUser must be used within a UserProvider");
  return ctx;
}
