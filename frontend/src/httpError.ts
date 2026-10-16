/** Only the local access guard can request LAN login; a provider's 401 cannot. */
export async function httpError(response: Response, fallback: string): Promise<Error> {
  const body = await response.json().catch(() => null);
  const data = body && typeof body === 'object' ? body : {};
  if (response.status === 401 && data.code === 'lan_auth_required')
    window.dispatchEvent(new Event('shunguang-auth-required'));
  return new Error(typeof data.detail === 'string' ? data.detail : fallback);
}
