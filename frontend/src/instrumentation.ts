// This machine sits behind a corporate HTTP(S) proxy (http_proxy/https_proxy
// env vars) required to reach the real internet (e.g. Google's OAuth
// endpoints). Unlike Python's `requests`, Node's native fetch (undici) does
// NOT read those env vars automatically, so outbound calls from NextAuth
// (and anything else using global fetch) would otherwise fail with
// "TypeError: fetch failed". EnvHttpProxyAgent makes fetch proxy-aware,
// matching the behavior already relied on throughout the Python backend.
export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const { setGlobalDispatcher, EnvHttpProxyAgent } = await import("undici");
    setGlobalDispatcher(new EnvHttpProxyAgent());
  }
}
