export type Role = "user" | "admin" | "superadmin";

export type Me = {
  id: string;
  email: string;
  name: string | null;
  picture: string | null;
  role: Role;
};

export const isAdmin = (u: Me | null) => u?.role === "admin" || u?.role === "superadmin";
export const isSuperadmin = (u: Me | null) => u?.role === "superadmin";

export const loginUrl = (returnTo: string) =>
  `/api/v1/auth/google/login?return_to=${encodeURIComponent(returnTo)}`;
