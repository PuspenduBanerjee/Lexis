import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { setCurrentUserId } from "../api/client";
import type { Role } from "../api/types";

export interface DemoUser {
  id: number;
  username: string;
  role: Role;
}

// The 3 users seeded by lexis_api/seed.py. Kept in sync manually - this is a
// stub auth UI, not a real user directory.
export const SEEDED_USERS: DemoUser[] = [
  { id: 1, username: "admin", role: "admin" },
  { id: 2, username: "editor1", role: "editor" },
  { id: 3, username: "viewer1", role: "viewer" },
];

const STORAGE_KEY = "lexis.currentUserId";

interface UserContextValue {
  user: DemoUser;
  setUserId: (id: number) => void;
}

const UserContext = createContext<UserContextValue | null>(null);

export function UserProvider({ children }: { children: ReactNode }) {
  const [userId, setUserId] = useState<number>(() => {
    const stored = Number(localStorage.getItem(STORAGE_KEY));
    return SEEDED_USERS.some((u) => u.id === stored) ? stored : SEEDED_USERS[0].id;
  });

  useEffect(() => {
    setCurrentUserId(userId);
    localStorage.setItem(STORAGE_KEY, String(userId));
  }, [userId]);

  const value = useMemo(
    () => ({
      user: SEEDED_USERS.find((u) => u.id === userId) ?? SEEDED_USERS[0],
      setUserId,
    }),
    [userId],
  );

  return <UserContext.Provider value={value}>{children}</UserContext.Provider>;
}

export function useUser(): UserContextValue {
  const ctx = useContext(UserContext);
  if (!ctx) throw new Error("useUser must be used within a UserProvider");
  return ctx;
}
