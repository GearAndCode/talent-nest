import React from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

// Same mark used on the TalentNest homepage header (pages/public/Home.jsx),
// duplicated here (not imported) because Home.jsx does not export it.
export const TalentNestLogo = ({ className = "w-6 h-6" }) => (
  <svg
    className={className}
    viewBox="0 0 32 32"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
  >
    <path
      d="M4 18C4 23.5228 8.47715 28 14 28H18C23.5228 28 28 23.5228 28 18C28 15.5 27.1 13.2 25.5 11.5"
      stroke="currentColor"
      strokeWidth="2.75"
      strokeLinecap="round"
    />
    <path
      d="M7 16C7 20.4183 10.5817 24 15 24H17C21.4183 24 25 20.4183 25 16"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeOpacity="0.75"
    />
    <circle cx="12" cy="11" r="2.5" fill="currentColor" />
    <path
      d="M9 17.5C9 15.5 10.3 14.5 12 14.5C13.7 14.5 15 15.5 15 17.5"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
    />
    <circle cx="20" cy="10" r="2.5" fill="currentColor" />
    <path
      d="M17 16.5C17 14.5 18.3 13.5 20 13.5C21.7 13.5 23 14.5 23 16.5"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
    />
  </svg>
);

/**
 * Minimal sticky header shared by the new billing/checkout pages. Mirrors
 * the "back" style header used on About.jsx/Careers.jsx rather than Home's
 * full animated nav, since these are secondary/task-focused pages.
 */
export function PublicHeader({ backTo = "/", backLabel = "Back to TalentNest" }) {
  const navigate = useNavigate();

  return (
    <header className="sticky top-0 z-50 bg-white/90 backdrop-blur-md border-b border-[#E2E8F0] shadow-sm">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <button
          onClick={() => navigate(backTo)}
          className="group flex items-center gap-2 text-sm font-medium text-[#475569] hover:text-[#0F766E] transition-colors"
        >
          <ArrowLeft className="w-4 h-4 transition-transform group-hover:-translate-x-1" />
          {backLabel}
        </button>

        <Link to="/" className="flex items-center gap-2.5" aria-label="TalentNest home">
          <div className="w-8 h-8 rounded-lg bg-[#0F766E] flex items-center justify-center text-white shadow-sm">
            <TalentNestLogo className="w-5 h-5 text-white" />
          </div>
          <span className="text-lg font-bold text-[#0F172A] tracking-tight">TalentNest</span>
        </Link>
      </div>
    </header>
  );
}

export function PublicFooter() {
  return (
    <footer className="border-t border-[#E2E8F0] bg-white py-8 mt-16">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-3 text-sm text-[#475569]">
        <span>© {new Date().getFullYear()} TalentNest. All rights reserved.</span>
        <div className="flex items-center gap-5">
          <Link to="/privacy-policy" className="hover:text-[#0F766E] transition-colors">
            Privacy Policy
          </Link>
          <Link to="/contact" className="hover:text-[#0F766E] transition-colors">
            Contact
          </Link>
        </div>
      </div>
    </footer>
  );
}
