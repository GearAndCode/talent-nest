import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Public - no auth required, powers the /plans page.
export const getPlans = () => api.get("/plans").then((r) => r.data);

// Authenticated (HR/company) endpoints.
export const getMySubscription = () => api.get("/subscription").then((r) => r.data);

export const createCheckout = (planCode) =>
  api.post("/checkout", { plan_code: planCode }).then((r) => r.data);

export const cancelSubscription = () =>
  api.post("/subscription/cancel").then((r) => r.data);

export const upgradeSubscription = (planCode) =>
  api.post("/subscription/upgrade", { plan_code: planCode }).then((r) => r.data);

// Renews the CURRENT plan for another billing period via a new PayFast
// checkout (PayFast's hosted checkout has no auto-charge API, so renewal
// is a fresh, customer-present checkout - see backend subscription.py).
export const renewSubscription = () =>
  api.post("/subscription/renew").then((r) => r.data);

export const getMyPayments = () => api.get("/payments").then((r) => r.data);

// Backend plan/entitlement restrictions (enforce_active_job_limit,
// enforce_application_limit, require_feature - see backend
// app/auth/plan_access.py) all raise HTTP 402 with a structured
// `detail` object: { error, message, limit, current_plan }. The
// `message` is already built server-side from the real plan name and
// limit, so the frontend never hardcodes a number here - it just
// surfaces what the backend sent.
//
// Any screen that can hit one of those 402s should run its caught
// error through this helper FIRST, before falling back to its normal
// "genuine error" handling, so a plan limit never gets mistaken for a
// generic failure (e.g. "Failed to save job. Please try again.") and
// a genuine 500 never gets mistaken for a plan limit.
//
// Returns null for anything that isn't a 402 plan/entitlement error
// (including a 402 with an unexpected shape falls back to a safe
// default message rather than returning null, since the status code
// alone is enough to know it's a plan restriction).
export function getPlanLimitInfo(error) {
  const response = error?.response;
  if (response?.status !== 402) return null;

  const detail = response.data?.detail;
  const detailIsObject = detail && typeof detail === "object" && !Array.isArray(detail);

  return {
    message:
      (detailIsObject && detail.message) ||
      (typeof detail === "string" ? detail : null) ||
      "You've reached a limit on your current plan. Upgrade your plan to continue.",
    errorType: detailIsObject ? detail.error || null : null,
    limit: detailIsObject ? detail.limit ?? null : null,
    currentPlan: detailIsObject ? detail.current_plan ?? null : null,
  };
}

export default api;
