import React from "react";
import { Link } from "react-router-dom";
import { CircleSlash } from "lucide-react";

import { PublicHeader, PublicFooter } from "../../components/public/PublicChrome";

export default function PaymentCancelled() {
  return (
    <div className="min-h-screen bg-[#F8FAFC] font-sans text-[#0F172A] antialiased flex flex-col">
      <PublicHeader backTo="/plans" backLabel="Back to plans" />

      <main className="flex-1 max-w-lg mx-auto w-full px-4 sm:px-6 lg:px-8 py-20 text-center">
        <CircleSlash className="w-12 h-12 text-[#475569] mx-auto" />
        <h1 className="mt-6 text-2xl font-bold text-[#0F172A]">Payment cancelled</h1>
        <p className="mt-3 text-[#475569]">No payment was completed.</p>
        <p className="mt-1 text-sm text-[#475569]">
          You can return to the plans page whenever you're ready.
        </p>

        <Link
          to="/plans"
          className="mt-8 inline-block rounded-xl bg-[#0F766E] px-6 py-3 text-sm font-semibold text-white hover:bg-[#0D9488] transition-colors"
        >
          Back to Plans
        </Link>
      </main>

      <PublicFooter />
    </div>
  );
}
