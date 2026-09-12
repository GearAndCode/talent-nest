import React from "react";
import { useNavigate } from "react-router-dom";
import { Lock } from "lucide-react";

/**
 * Renders in place of a premium widget/section when the backend has
 * returned 402 Payment Required for that feature. The backend is always
 * the source of truth for the lock - this component never itself decides
 * whether a feature should be enabled.
 */
export default function PremiumFeatureLock({
  title = "Premium Feature",
  description = "Upgrade your plan to unlock this feature.",
  ctaLabel = "Upgrade to Professional",
}) {
  const navigate = useNavigate();

  return (
    <div className="rounded-2xl border border-[#E2E8F0] bg-white shadow-sm p-10 text-center">
      <div className="w-12 h-12 rounded-full bg-[#0F766E]/10 text-[#0F766E] flex items-center justify-center mx-auto">
        <Lock className="w-5 h-5" />
      </div>
      <span className="mt-4 inline-block text-xs font-semibold uppercase tracking-wide text-[#0F766E]">
        Premium Feature
      </span>
      <h3 className="mt-2 text-lg font-semibold text-[#0F172A]">{title}</h3>
      <p className="mt-2 text-sm text-[#475569] max-w-md mx-auto">{description}</p>
      <button
        onClick={() => navigate("/plans")}
        className="mt-6 rounded-xl bg-[#0F766E] px-5 py-2.5 text-sm font-semibold text-white hover:bg-[#0D9488] transition-colors"
      >
        {ctaLabel}
      </button>
    </div>
  );
}
