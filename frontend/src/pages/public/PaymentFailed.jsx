import React from "react";
import { Link } from "react-router-dom";
import { XCircle } from "lucide-react";

import { PublicHeader, PublicFooter } from "../../components/public/PublicChrome";

export default function PaymentFailed() {
  return (
    <div className="min-h-screen bg-[#F8FAFC] font-sans text-[#0F172A] antialiased flex flex-col">
      <PublicHeader backTo="/plans" backLabel="Back to plans" />

      <main className="flex-1 max-w-lg mx-auto w-full px-4 sm:px-6 lg:px-8 py-20 text-center">
        <XCircle className="w-12 h-12 text-red-500 mx-auto" />
        <h1 className="mt-6 text-2xl font-bold text-[#0F172A]">Payment unsuccessful</h1>
        <p className="mt-3 text-[#475569]">Your payment could not be completed.</p>
        <p className="mt-1 text-sm text-[#475569]">No premium subscription has been activated.</p>

        <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-3">
          <Link
            to="/plans"
            className="w-full sm:w-auto rounded-xl bg-[#0F766E] px-6 py-3 text-sm font-semibold text-white hover:bg-[#0D9488] transition-colors"
          >
            Try Again
          </Link>
          <Link
            to="/plans"
            className="w-full sm:w-auto rounded-xl border border-[#E2E8F0] bg-white px-6 py-3 text-sm font-semibold text-[#0F172A] hover:bg-[#F8FAFC] transition-colors"
          >
            View Plans
          </Link>
        </div>
      </main>

      <PublicFooter />
    </div>
  );
}
