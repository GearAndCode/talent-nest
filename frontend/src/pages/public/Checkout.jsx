import React, { useEffect, useState } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { Check, Loader2, ShieldCheck, AlertTriangle } from "lucide-react";
import toast, { Toaster } from "react-hot-toast";

import { PublicHeader, PublicFooter } from "../../components/public/PublicChrome";
import { PLAN_DISPLAY, PENDING_PLAN_KEY, PENDING_TRANSACTION_KEY } from "../../config/plans";
import { getPlans, createCheckout } from "../../services/subscriptionService";

export default function Checkout() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const planCode = searchParams.get("plan");

  const [plan, setPlan] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");

  useEffect(() => {
    window.scrollTo(0, 0);

    if (!localStorage.getItem("access_token")) {
      // Checkout must be tied to an authenticated company account. Preserve
      // the plan and send the user to log in, then come straight back.
      if (planCode) localStorage.setItem(PENDING_PLAN_KEY, planCode);
      navigate("/hr-login");
      return;
    }

    if (!planCode) {
      navigate("/plans");
      return;
    }

    getPlans()
      .then((plans) => {
        const found = plans.find((p) => p.code === planCode);
        if (!found) {
          setLoadError("That plan could not be found.");
        } else if (found.code === "starter") {
          navigate("/hr-dashboard");
        } else {
          setPlan(found);
        }
      })
      .catch(() => setLoadError("Could not load plan details right now."));
  }, [planCode, navigate]);

  const handleProceedToPayment = async () => {
    if (submitting) return; // guard against double-submit / duplicate sessions
    setSubmitting(true);
    setSubmitError("");

    try {
      const session = await createCheckout(plan.code);
      // Remember which transaction THIS checkout attempt created, so that
      // when the browser lands back on /payment-success we know exactly
      // which payment to ask the backend about - never a value read from
      // a URL parameter, which anyone could edit by hand.
      if (session.transaction_id) {
        localStorage.setItem(PENDING_TRANSACTION_KEY, session.transaction_id);
      }
      // The browser is redirected to PayFast's real hosted checkout page.
      // Nothing here marks the subscription as active - that only happens
      // once PayFast's server-to-server webhook confirms payment.
      window.location.href = session.checkout_url;
    } catch (err) {
      const detail = err?.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : detail?.message ||
            "Could not start checkout with the payment provider. Please try again.";
      setSubmitError(message);
      setSubmitting(false);
      toast.error(message);
    }
  };

  const display = plan ? PLAN_DISPLAY[plan.code] || {} : {};

  return (
    <div className="min-h-screen bg-[#F8FAFC] font-sans text-[#0F172A] antialiased flex flex-col">
      <Toaster position="top-center" />
      <PublicHeader backTo="/plans" backLabel="Back to plans" />

      <main className="flex-1 max-w-2xl mx-auto w-full px-4 sm:px-6 lg:px-8 py-14">
        <h1 className="text-2xl sm:text-3xl font-bold text-[#0F172A] text-center">
          Complete your subscription
        </h1>

        {loadError && (
          <div className="mt-8 flex flex-col items-center gap-3 text-center">
            <AlertTriangle className="w-6 h-6 text-red-500" />
            <p className="text-sm text-[#475569]">{loadError}</p>
            <Link to="/plans" className="text-sm font-semibold text-[#0F766E] hover:underline">
              Back to plans
            </Link>
          </div>
        )}

        {!plan && !loadError && (
          <div className="flex justify-center py-16">
            <Loader2 className="w-6 h-6 text-[#0F766E] animate-spin" />
          </div>
        )}

        {plan && (
          <div className="mt-8 rounded-2xl border border-[#E2E8F0] bg-white shadow-sm overflow-hidden">
            <div className="p-8">
              <div className="flex items-baseline justify-between">
                <h2 className="text-lg font-semibold text-[#0F172A]">{plan.name} Plan</h2>
                <div className="text-right">
                  <span className="text-2xl font-bold text-[#0F172A]">
                    ${Number(plan.price).toFixed(2)}
                  </span>
                  <span className="text-sm text-[#475569]"> / {plan.billing_interval}</span>
                </div>
              </div>

              <ul className="mt-6 space-y-2.5">
                {(display.bullets || []).map((b) => (
                  <li key={b} className="flex items-start gap-2 text-sm text-[#0F172A]">
                    <Check className="w-4 h-4 text-[#0F766E] mt-0.5 shrink-0" />
                    {b}
                  </li>
                ))}
              </ul>
            </div>

            <div className="border-t border-[#E2E8F0] bg-[#F8FAFC] px-8 py-6">
              <div className="flex items-center justify-between text-base font-semibold text-[#0F172A]">
                <span>Total</span>
                <span>
                  ${Number(plan.price).toFixed(2)} / {plan.billing_interval}
                </span>
              </div>

              <p className="mt-3 flex items-center gap-1.5 text-xs text-[#475569]">
                <ShieldCheck className="w-3.5 h-3.5 text-[#0F766E]" />
                You'll be redirected to PayFast's secure payment page to complete your purchase.
              </p>

              {submitError && (
                <p className="mt-3 text-sm text-red-600">{submitError}</p>
              )}

              <button
                onClick={handleProceedToPayment}
                disabled={submitting}
                className="mt-5 w-full rounded-xl bg-[#0F766E] px-4 py-3 text-sm font-semibold text-white hover:bg-[#0D9488] transition-colors disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2"
              >
                {submitting && <Loader2 className="w-4 h-4 animate-spin" />}
                {submitting ? "Redirecting to payment..." : "Proceed to Payment"}
              </button>
            </div>
          </div>
        )}
      </main>

      <PublicFooter />
    </div>
  );
}
