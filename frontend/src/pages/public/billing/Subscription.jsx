import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Loader2,
  CheckCircle2,
  AlertCircle,
  CreditCard,
  Briefcase,
} from "lucide-react";
import toast, { Toaster } from "react-hot-toast";

import HRShell from "../../../components/hr/HRShell";

import {
  getMySubscription,
  getMyPayments,
  cancelSubscription,
  renewSubscription,
  upgradeSubscription,
} from "../../../services/subscriptionService";
import { PENDING_TRANSACTION_KEY } from "../../../config/plans";

function formatDate(value) {
  if (!value) return "—";

  return new Date(value).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

const STATUS_STYLES = {
  active: "bg-[#0F766E]/10 text-[#0F766E]",
  trialing: "bg-[#0F766E]/10 text-[#0F766E]",
  past_due: "bg-amber-100 text-amber-700",
  cancelled: "bg-red-100 text-red-700",
  expired: "bg-red-100 text-red-700",
};

export default function Subscription() {
  const navigate = useNavigate();

  const [subscription, setSubscription] = useState(null);
  const [payments, setPayments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionLoading, setActionLoading] = useState(false);

  const load = () => {
    setLoading(true);
    setError("");

    Promise.all([
      getMySubscription(),
      getMyPayments(),
    ])
      .then(([sub, pays]) => {
        setSubscription(sub);
        setPayments(pays);
      })
      .catch(() => {
        setError(
          "Could not load your subscription right now."
        );
      })
      .finally(() => {
        setLoading(false);
      });
  };

  useEffect(() => {
    if (!localStorage.getItem("access_token")) {
      navigate("/hr-login");
      return;
    }

    load();

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleCancel = async () => {
    const confirmed = window.confirm(
      "Cancel your subscription? You'll keep access until the end of your current billing period."
    );

    if (!confirmed) {
      return;
    }

    setActionLoading(true);

    try {
      const updated = await cancelSubscription();

      setSubscription(updated);

      toast.success(
        "Your subscription will not renew after the current period."
      );
    } catch {
      toast.error(
        "Could not cancel your subscription. Please try again."
      );
    } finally {
      setActionLoading(false);
    }
  };

  const handleRenew = async () => {
    setActionLoading(true);

    try {
      const session = await renewSubscription();

      if (!session?.checkout_url) {
        throw new Error("Checkout URL was not returned.");
      }

      window.location.href = session.checkout_url;
    } catch (err) {
      const detail = err?.response?.data?.detail;

      toast.error(
        typeof detail === "string"
          ? detail
          : detail?.message || "Could not start renewal checkout."
      );

      setActionLoading(false);
    }
  };

  const handleUpgrade = async (planCode) => {
    setActionLoading(true);

    try {
      const session = await upgradeSubscription(planCode);

      if (!session?.checkout_url) {
        throw new Error("Checkout URL was not returned.");
      }

      // Remember which transaction this upgrade attempt created, exactly
      // like Checkout.jsx does for a first-time subscribe, so that when
      // the browser lands back on /payment-success it knows which
      // payment to confirm instead of reporting "no payment in progress".
      if (session.transaction_id) {
        localStorage.setItem(PENDING_TRANSACTION_KEY, session.transaction_id);
      }

      window.location.href = session.checkout_url;
    } catch (err) {
      const detail = err?.response?.data?.detail;

      toast.error(
        typeof detail === "string"
          ? detail
          : detail?.message || "Could not start checkout."
      );

      setActionLoading(false);
    }
  };

  return (
    <HRShell>
      <Toaster position="top-center" />

      <div className="max-w-4xl mx-auto">

        <h1 className="text-2xl font-bold text-[#0F172A]">
          Your Subscription
        </h1>

        <p className="mt-1 text-sm text-[#475569]">
          Manage your TalentNest plan, usage limits, and billing history.
        </p>

        {loading && (
          <div className="flex justify-center py-20">
            <Loader2 className="w-6 h-6 text-[#0F766E] animate-spin" />
          </div>
        )}

        {error && !loading && (
          <div className="mt-8 flex items-center gap-2 text-sm text-red-600">
            <AlertCircle className="w-4 h-4" />
            {error}
          </div>
        )}

        {subscription && !loading && (
          <>
            {/* Plan Summary */}
            <div className="mt-6 rounded-2xl border border-[#E2E8F0] bg-white shadow-sm p-6 sm:p-8">

              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">

                <div>
                  <p className="text-sm text-[#475569]">
                    Current plan
                  </p>

                  <h2 className="text-2xl font-bold text-[#0F172A] mt-1">
                    {subscription.plan.name}

                    {subscription.plan.price > 0 && (
                      <span className="text-base font-medium text-[#475569]">
                        {" "}
                        · $
                        {Number(subscription.plan.price).toFixed(0)}
                        /{subscription.plan.billing_interval}
                      </span>
                    )}

                    {subscription.plan.price === 0 && (
                      <span className="text-base font-medium text-[#475569]">
                        {" "}
                        · Free
                      </span>
                    )}
                  </h2>
                </div>

                <span
                  className={`inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-full ${
                    STATUS_STYLES[subscription.status] ||
                    "bg-[#F8FAFC] text-[#475569]"
                  }`}
                >
                  <CheckCircle2 className="w-3.5 h-3.5" />

                  {subscription.status === "active" &&
                  subscription.cancel_at_period_end
                    ? "Active (cancelling at period end)"
                    : subscription.status.replace("_", " ")}
                </span>

              </div>

              {subscription.current_period_start &&
                subscription.current_period_end && (
                  <p className="mt-4 text-sm text-[#475569]">
                    Current billing period:{" "}

                    <span className="font-medium text-[#0F172A]">
                      {formatDate(
                        subscription.current_period_start
                      )}{" "}
                      –{" "}
                      {formatDate(
                        subscription.current_period_end
                      )}
                    </span>
                  </p>
                )}

              <div className="mt-5 flex items-center gap-2 text-sm text-[#0F172A]">
                <Briefcase className="w-4 h-4 text-[#0F766E]" />

                {subscription.active_jobs_used} /{" "}
                {subscription.plan.max_active_jobs} active jobs used
              </div>

              <div className="mt-6 flex flex-wrap gap-3">

                {subscription.plan.code !== "starter" && (
                  <button
                    disabled={actionLoading}
                    onClick={handleRenew}
                    className="rounded-xl bg-white border border-[#0F766E] px-5 py-2.5 text-sm font-semibold text-[#0F766E] hover:bg-[#0F766E]/5 transition-colors disabled:opacity-60"
                  >
                    Renew Now
                  </button>
                )}

                {subscription.plan.code !== "business" && (
                  <button
                    disabled={actionLoading}
                    onClick={() =>
                      handleUpgrade(
                        subscription.plan.code === "starter"
                          ? "professional"
                          : "business"
                      )
                    }
                    className="rounded-xl bg-[#0F766E] px-5 py-2.5 text-sm font-semibold text-white hover:bg-[#0D9488] transition-colors disabled:opacity-60"
                  >
                    {subscription.plan.code === "starter"
                      ? "Upgrade to Professional"
                      : "Upgrade to Business"}
                  </button>
                )}

                {subscription.plan.code !== "starter" &&
                  !subscription.cancel_at_period_end && (
                    <button
                      disabled={actionLoading}
                      onClick={handleCancel}
                      className="rounded-xl border border-[#E2E8F0] bg-white px-5 py-2.5 text-sm font-semibold text-[#475569] hover:bg-[#F8FAFC] transition-colors disabled:opacity-60"
                    >
                      Cancel Subscription
                    </button>
                  )}

              </div>
            </div>

            {/* Payment History */}
            <div className="mt-8 rounded-2xl border border-[#E2E8F0] bg-white shadow-sm overflow-hidden">

              <div className="px-6 py-4 border-b border-[#E2E8F0] flex items-center gap-2">
                <CreditCard className="w-4 h-4 text-[#0F766E]" />

                <h3 className="text-sm font-semibold text-[#0F172A]">
                  Payment History
                </h3>
              </div>

              {payments.length === 0 ? (
                <p className="px-6 py-8 text-sm text-[#475569] text-center">
                  No payments yet.
                </p>
              ) : (
                <div className="overflow-x-auto">

                  <table className="w-full text-sm">

                    <thead>
                      <tr className="text-left text-[#475569] border-b border-[#E2E8F0]">

                        <th className="px-6 py-3 font-medium">
                          Date
                        </th>

                        <th className="px-6 py-3 font-medium">
                          Plan
                        </th>

                        <th className="px-6 py-3 font-medium">
                          Amount
                        </th>

                        <th className="px-6 py-3 font-medium">
                          Status
                        </th>

                      </tr>
                    </thead>

                    <tbody>
                      {payments.map((p) => (
                        <tr
                          key={p.id}
                          className="border-b border-[#E2E8F0] last:border-0"
                        >

                          <td className="px-6 py-3 text-[#0F172A]">
                            {formatDate(p.created_at)}
                          </td>

                          <td className="px-6 py-3 text-[#0F172A]">
                            {p.plan_name || "—"}
                            {p.is_renewal && (
                              <span className="ml-2 inline-flex text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full bg-[#0F172A]/5 text-[#475569]">
                                Renewal
                              </span>
                            )}
                          </td>

                          <td className="px-6 py-3 text-[#0F172A]">
                            $
                            {Number(p.amount).toFixed(2)}{" "}
                            {p.currency}
                          </td>

                          <td className="px-6 py-3">

                            <span
                              className={`inline-flex text-xs font-semibold px-2.5 py-1 rounded-full ${
                                p.status === "paid"
                                  ? "bg-[#0F766E]/10 text-[#0F766E]"
                                  : p.status === "pending"
                                  ? "bg-amber-100 text-amber-700"
                                  : "bg-red-100 text-red-700"
                              }`}
                            >
                              {p.status}
                            </span>

                          </td>

                        </tr>
                      ))}
                    </tbody>

                  </table>

                </div>
              )}

            </div>
          </>
        )}

      </div>
    </HRShell>
  );
}