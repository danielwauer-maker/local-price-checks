export function useAuth() {
  return {
    session: null,
    user: null,
    loading: false,
    signOut: async () => undefined,
  };
}
