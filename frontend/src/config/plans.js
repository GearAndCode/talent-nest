export const PLAN_DISPLAY = {
  starter: {
    tagline: "For individuals getting started with TalentNest",
    bullets: [
      "1 active job",
      "25 applications per job",
      "Basic HR dashboard",
      "Candidate management",
      "Application management",
    ],
    cta: "Get Started",
  },
  professional: {
    tagline: "For recruiters who want AI-powered hiring",
    bullets: [
      "5 active jobs",
      "200 applications per job",
      "AI Resume Analysis",
      "AI Candidate Ranking",
      "AI Recommendations",
      "AI Interview Questions",
      "Advanced analytics",
    ],
    cta: "Subscribe",
  },
  business: {
    tagline: "For growing recruitment teams",
    bullets: [
      "15 active jobs",
      "1,000 applications per job",
      "All Professional features",
      "Multiple recruiters",
      "Advanced analytics",
      "Higher AI usage",
    ],
    cta: "Subscribe",
  },
};

export const PENDING_PLAN_KEY = "tn_pending_checkout_plan";

// The transaction_id our own backend generated for the checkout session
// currently in flight. Set by Checkout.jsx right before redirecting to
// PayFast, read by PaymentSuccess.jsx to look up THIS payment's real
// status from the backend. This never comes from a URL parameter - a
// visitor editing the URL of /payment-success cannot influence which
// transaction gets looked up, let alone its status.
export const PENDING_TRANSACTION_KEY = "tn_pending_checkout_transaction_id";
