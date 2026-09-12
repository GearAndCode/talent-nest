import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Check, Loader2, Sparkles } from "lucide-react";
import toast, { Toaster } from "react-hot-toast";

import { PublicHeader, PublicFooter } from "../../components/public/PublicChrome";
import { PLAN_DISPLAY, PENDING_PLAN_KEY } from "../../config/plans";
import { getPlans } from "../../services/subscriptionService";

export default function Plans() {
  const navigate = useNavigate();
  const [plans, setPlans] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    window.scrollTo(0, 0);
    getPlans()
      .then((data) => setPlans([...data].sort((a, b) => a.id - b.id)))
      .catch(() => setError("Could not load plans right now. Please refresh the page."));
  }, []);

  const handleSelectPlan = (plan) => {
    if (plan.code === "starter") {
      // Starter is free - it never touches checkout/payment. Take the
      // user straight into the normal free HR onboarding flow.
      const token = localStorage.getItem("access_token");
      navigate(token ? "/hr-dashboard" : "/hr-login");
      return;
    }

    const token = localStorage.getItem("access_token");
    if (!token) {
      // Preserve the chosen plan so the user isn't asked to choose again
      // after logging in - HRLogin.jsx checks this key on success and
      // redirects straight back into checkout.
      localStorage.setItem(PENDING_PLAN_KEY, plan.code);
      toast("Log in to your HR account to continue checkout.", { icon: "🔒" });
      navigate("/hr-login");
      return;
    }

    navigate(`/checkout?plan=${plan.code}`);
  };

  return (
    <div className="min-h-screen bg-[#F8FAFC] font-sans text-[#0F172A] antialiased flex flex-col">
      <Toaster position="top-center" />
      <PublicHeader />

      <main className="flex-1">
        {/* Hero */}
        <section className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 pt-16 pb-10 text-center">
          <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#0F766E] bg-[#0F766E]/10 px-3 py-1 rounded-full">
            <Sparkles className="w-3.5 h-3.5" />
            Simple, transparent pricing
          </span>
          <h1 className="mt-5 text-3xl sm:text-4xl font-bold tracking-tight text-[#0F172A]">
            Choose the plan that fits your hiring needs
          </h1>
          <p className="mt-4 text-base sm:text-lg text-[#475569] max-w-2xl mx-auto">
            Start hiring smarter with TalentNest's AI-powered recruitment tools.
          </p>
        </section>

        {/* Pricing cards */}
        <section className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pb-24">
          {error && (
            <p className="text-center text-sm text-red-600 mb-6">{error}</p>
          )}

          {!plans && !error ? (
            <div className="flex justify-center py-20">
              <Loader2 className="w-6 h-6 text-[#0F766E] animate-spin" />
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-start">
              {plans?.map((plan) => {
                const display = PLAN_DISPLAY[plan.code] || {};
                const popular = plan.is_most_popular;

                return (
                  <div
                    key={plan.code}
                    className={`relative rounded-2xl border bg-white p-8 flex flex-col shadow-sm transition-shadow hover:shadow-md ${
                      popular
                        ? "border-[#0F766E] ring-2 ring-[#0F766E]/30 md:-translate-y-2"
                        : "border-[#E2E8F0]"
                    }`}
                  >
                    {popular && (
                      <span className="absolute -top-3 left-1/2 -translate-x-1/2 bg-[#0F766E] text-white text-xs font-semibold px-3 py-1 rounded-full shadow-sm">
                        MOST POPULAR
                      </span>
                    )}

                    <h2 className="text-lg font-semibold text-[#0F172A]">{plan.name}</h2>
                    <p className="mt-1 text-sm text-[#475569] min-h-[40px]">{display.tagline}</p>

                    <div className="mt-5 flex items-baseline gap-1">
                      <span className="text-4xl font-bold text-[#0F172A]">
                        ${Number(plan.price).toFixed(0)}
                      </span>
                      <span className="text-sm text-[#475569]">/{plan.billing_interval}</span>
                    </div>

                    <ul className="mt-6 space-y-3 flex-1">
                      {(display.bullets || []).map((b) => (
                        <li key={b} className="flex items-start gap-2 text-sm text-[#0F172A]">
                          <Check className="w-4 h-4 text-[#0F766E] mt-0.5 shrink-0" />
                          {b}
                        </li>
                      ))}
                    </ul>

                    <button
                      onClick={() => handleSelectPlan(plan)}
                      className={`mt-8 w-full rounded-xl px-4 py-2.5 text-sm font-semibold transition-colors ${
                        popular
                          ? "bg-[#0F766E] text-white hover:bg-[#0D9488]"
                          : "bg-[#F8FAFC] text-[#0F172A] border border-[#E2E8F0] hover:bg-[#E2E8F0]"
                      }`}
                    >
                      {display.cta || "Choose Plan"}
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </main>

      <PublicFooter />
    </div>
  );
}
