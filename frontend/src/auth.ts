import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

// Replaces app.py's manual OAuth2Component + unverified base64 JWT decode.
// Auth.js verifies Google's ID token signature properly (a real security
// fix over the old Streamlit flow) and manages the session cookie itself.
export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [Google],
  session: { strategy: "jwt" },
  pages: {
    signIn: "/",
  },
});
