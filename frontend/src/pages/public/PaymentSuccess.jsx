import React, { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { CheckCircle2, Loader2, Clock, XCircle, CircleSlash, HelpCircle } from "lucide-react";

import { PublicHeader, PublicFooter } from "../../components/public/PublicChrome";
import { getMyPayments } from "../../services/subscriptionService";
import { PENDING_TRANSACTION_KEY } from "../../config/plans";

const POLL_INTERVAL_MS = 3000;
const MAX_ATTEMPTS = 15; // ~45 seconds

// status: checking | active | failed | cancelled | timeout | error | not_found
export default function PaymentSuccess() {
  const navigate = useNavigate();
  const [payment, setPayment] = useState(null);
  const [status, setStatus] = useState("checking");
  const attemptsRef = useRef(0);

  useEffect(() => {
    window.scrollTo(0, 0);

    if (!localStorage.getItem("access_token")) {
      navigate("/hr-login");
      return;
    }

    // Which payment are we confirming? This comes ONLY from what our own
    // client code stored right before redirecting to PayFast (see
    // Checkout.jsx) - never from this page's own URL. A visitor who edits
    // the URL of /payment-success (or bookmarks/shares it) has no way to
    // point this page at a payment that isn't their own or that they
    // didn't actually just attempt, and this page never treats "the
    // browser landed here" as proof of anything by itself.
    const transactionId = localStorage.getItem(PENDING_TRANSACTION_KEY);

    let cancelled = false;
    let timer;

    const poll = async () => {
      if (!transactionId) {
        if (!cancelled) setStatus("not_found");
        return;
      }

      attemptsRef.current += 1;
      try {
        const payments = await getMyPayments();
        if (cancelled) return;

        // getMyPayments() is scoped to the logged-in company by the
        // backend, so this can only ever resolve to a payment that
        // belongs to this company - never someone else's.
        const match = payments.find((p) => p.transaction_id === transactionId);

        if (match && match.status === "paid") {
          setPayment(match);
          setStatus("active");
          localStorage.removeItem(PENDING_TRANSACTION_KEY);
          return;
        }

        if (match && match.status === "failed") {
          setPayment(match);
          setStatus("failed");
          localStorage.removeItem(PENDING_TRANSACTION_KEY);
          return;
        }

        if (match && match.status === "cancelled") {
          setPayment(match);
          setStatus("cancelled");
          localStorage.removeItem(PENDING_TRANSACTION_KEY);
          return;
        }

        // Still "pending" (or the row hasn't shown up yet) - the PayFast
        // webhook, which is the only thing that ever changes this, simply
        // hasn't run yet. Keep showing the "verifying" state instead of
        // guessing at success.
        if (attemptsRef.current >= MAX_ATTEMPTS) {
          setStatus("timeout");
          return;
        }

        timer = setTimeout(poll, POLL_INTERVAL_MS);
      } catch {
        if (!cancelled) setStatus("error");
      }
    };

    poll();

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [navigate]);

  return (
    <div className="min-h-screen bg-[#F8FAFC] font-sans text-[#0F172A] antialiased flex flex-col">
      <PublicHeader backTo="/plans" backLabel="Back to plans" />

      <main className="flex-1 max-w-lg mx-auto w-full px-4 sm:px-6 lg:px-8 py-20 text-center">
        {status === "checking" && (
          <>
            <Loader2 className="w-10 h-10 text-[#0F766E] animate-spin mx-auto" />
            <h1 className="mt-6 text-xl font-semibold text-[#0F172A]">
              We're confirming your payment...
            </h1>
            <p className="mt-2 text-sm text-[#475569]">
              Please wait while we verify your transaction with the payment provider.
              This usually takes a few seconds.
            </p>
          </>
        )}

        {status === "active" && payment && (
          <>
            <CheckCircle2 className="w-12 h-12 text-[#0F766E] mx-auto" />
            <h1 className="mt-6 text-2xl font-bold text-[#0F172A]">Payment Successful</h1>
            <p className="mt-3 text-[#475569]">
              Your {payment.plan_name || "new"} subscription is now active.
            </p>
            <p className="mt-1 text-sm text-[#475569]">
              You can now access TalentNest's premium AI recruitment features.
            </p>
            <Link
              to="/hr-dashboard"
              className="mt-8 inline-block rounded-xl bg-[#0F766E] px-6 py-3 text-sm font-semibold text-white hover:bg-[#0D9488] transition-colors"
            >
              Go to HR Dashboard
            </Link>
          </>
        )}

        {status === "failed" && (
          <>
            <XCircle className="w-12 h-12 text-red-500 mx-auto" />
            <h1 className="mt-6 text-2xl font-bold text-[#0F172A]">Payment unsuccessful</h1>
            <p className="mt-3 text-[#475569]">Your payment could not be completed.</p>
            <p className="mt-1 text-sm text-[#475569]">No premium subscription has been activated.</p>
            <Link
              to="/plans"
              className="mt-8 inline-block rounded-xl bg-[#0F766E] px-6 py-3 text-sm font-semibold text-white hover:bg-[#0D9488] transition-colors"
            >
              Try Again
            </Link>
          </>
        )}

        {status === "cancelled" && (
          <>
            <CircleSlash className="w-12 h-12 text-[#475569] mx-auto" />
            <h1 className="mt-6 text-2xl font-bold text-[#0F172A]">Payment cancelled</h1>
            <p className="mt-3 text-[#475569]">No payment was completed.</p>
            <Link
              to="/plans"
              className="mt-8 inline-block rounded-xl bg-[#0F766E] px-6 py-3 text-sm font-semibold text-white hover:bg-[#0D9488] transition-colors"
            >
              Back to Plans
            </Link>
          </>
        )}

        {status === "timeout" && (
          <>
            <Clock className="w-10 h-10 text-amber-500 mx-auto" />
            <h1 className="mt-6 text-xl font-semibold text-[#0F172A]">
              Still confirming your payment
            </h1>
            <p className="mt-2 text-sm text-[#475569]">
              Your payment may still be processing on the provider's side. This can
              take a few minutes. Check your subscription status - it will update
              automatically once confirmed.
            </p>
            <Link
              to="/subscription"
              className="mt-8 inline-block rounded-xl bg-[#0F766E] px-6 py-3 text-sm font-semibold text-white hover:bg-[#0D9488] transition-colors"
            >
              Check subscription status
            </Link>
          </>
        )}

        {status === "not_found" && (
          <>
            <HelpCircle className="w-10 h-10 text-[#475569] mx-auto" />
            <h1 className="mt-6 text-xl font-semibold text-[#0F172A]">
              No payment in progress
            </h1>
            <p className="mt-2 text-sm text-[#475569]">
              We couldn't find a checkout session for this browser. If you just paid,
              check your subscription status below - it updates automatically once
              PayFast confirms the payment.
            </p>
            <Link
              to="/subscription"
              className="mt-8 inline-block rounded-xl bg-[#0F766E] px-6 py-3 text-sm font-semibold text-white hover:bg-[#0D9488] transition-colors"
            >
              Check subscription status
            </Link>
          </>
        )}

        {status === "error" && (
          <>
            <Clock className="w-10 h-10 text-red-500 mx-auto" />
            <h1 className="mt-6 text-xl font-semibold text-[#0F172A]">
              Couldn't check your payment status
            </h1>
            <p className="mt-2 text-sm text-[#475569]">
              Please check your subscription page in a moment, or contact support if
              the issue continues.
            </p>
            <Link
              to="/subscription"
              className="mt-8 inline-block rounded-xl bg-[#0F172A] px-6 py-3 text-sm font-semibold text-white hover:bg-[#1e293b] transition-colors"
            >
              Go to Subscription page
            </Link>
          </>
        )}
      </main>

      <PublicFooter />
    </div>
  );
}
