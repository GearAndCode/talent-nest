import { Routes, Route } from "react-router-dom";

// ==================== PUBLIC PAGES ====================
import Contact from "../pages/public/Contact.jsx";
import Home from "../pages/public/Home.jsx";
import Careers from "../pages/public/Careers.jsx";
import About from "../pages/public/About.jsx";
import PrivacyPolicy from "../pages/public/PrivacyPolicy.jsx";
import Plans from "../pages/public/Plans.jsx";
import Checkout from "../pages/public/Checkout.jsx";
import PaymentSuccess from "../pages/public/PaymentSuccess.jsx";
import PaymentFailed from "../pages/public/PaymentFailed.jsx";
import PaymentCancelled from "../pages/public/PaymentCancelled.jsx";

// ==================== AUTHENTICATION ====================
import HRLogin from "../pages/auth/HRlogin.jsx";
import CandidateLogin from "../pages/auth/CandidateLogin.jsx";
import CandidateRegister from "../pages/auth/CandidateRegister.jsx";

// ==================== HR PORTAL ====================
import HRDashboard from "../pages/hr/HRDashboard.jsx";
import Jobs from "../pages/hr/Jobs.jsx";
import Applications from "../pages/hr/Applications.jsx";
import Candidates from "../pages/hr/Candidates.jsx";
import Aianalysis from "../pages/hr/Aianalysis.jsx";
import AIRankings from "../pages/hr/AIRankings.jsx";

// IMPORTANT:
// Subscription.jsx is actually inside:
// src/pages/public/billing/Subscription.jsx
import Subscription from "../pages/public/billing/Subscription.jsx";
// ==================== CANDIDATE PORTAL ====================
import CandidateDashboard from "../pages/candidate/CandidateDashboard.jsx";
import BrowseJobs from "../pages/candidate/BrowseJobs.jsx";
import JobDetails from "../pages/candidate/JobDetails.jsx";
import MyApplications from "../pages/candidate/MyApplications.jsx";
import AIAnalysis from "../pages/candidate/AIAnalysis.jsx";
import Profile from "../pages/candidate/Profile.jsx";
import RequestHRAccess from "../pages/auth/RequestHrAccess.jsx";
import ApplyJob from "../pages/candidate/ApplyJob.jsx";

export default function AppRoutes() {
  return (
    <Routes>

      {/* ==================== PUBLIC PAGES ==================== */}

      <Route path="/" element={<Home />} />
      <Route path="/careers" element={<Careers />} />
      <Route path="/about" element={<About />} />
      <Route path="/contact" element={<Contact />} />
      <Route path="/privacy-policy" element={<PrivacyPolicy />} />

      {/* ==================== SUBSCRIPTION & BILLING ==================== */}

      <Route path="/plans" element={<Plans />} />
      <Route path="/checkout" element={<Checkout />} />
      <Route path="/payment-success" element={<PaymentSuccess />} />
      <Route path="/payment-failed" element={<PaymentFailed />} />
      <Route path="/payment-cancelled" element={<PaymentCancelled />} />
      <Route path="/subscription" element={<Subscription />} />

      {/* ==================== AUTHENTICATION ==================== */}

      <Route path="/hr-login" element={<HRLogin />} />
      <Route path="/candidate-login" element={<CandidateLogin />} />
      <Route path="/candidate-register" element={<CandidateRegister />} />

      {/* ==================== HR PORTAL ==================== */}

      <Route path="/hr-dashboard" element={<HRDashboard />} />
      <Route path="/jobs" element={<Jobs />} />
      <Route path="/applications" element={<Applications />} />
      <Route path="/candidates" element={<Candidates />} />
      <Route path="/ai-analysis" element={<Aianalysis />} />
      <Route path="/ai-rankings" element={<AIRankings />} />

      {/* ==================== CANDIDATE PORTAL ==================== */}

      {/* Dashboard */}
      <Route
        path="/dashboard"
        element={<CandidateDashboard />}
      />

      {/* Candidate Dashboard alternative URL */}
      <Route
        path="/candidate/dashboard"
        element={<CandidateDashboard />}
      />

      {/* Browse Jobs */}
      <Route
        path="/browse-jobs"
        element={<BrowseJobs />}
      />

      {/* Candidate Browse Jobs */}
      <Route
        path="/candidate/browse-jobs"
        element={<BrowseJobs />}
      />

      {/* Old Browse Jobs URL */}
      <Route
        path="/candidate/BrowseJobs"
        element={<BrowseJobs />}
      />

      {/* Job Details */}
      <Route
        path="/candidate/jobs/:jobId"
        element={<JobDetails />}
      />

      {/* My Applications */}
      <Route
        path="/candidate/applications"
        element={<MyApplications />}
      />

      {/* My Applications alternative URL */}
      <Route
        path="/candidate/my-applications"
        element={<MyApplications />}
      />

      {/* ==================== AI RESUME ANALYSIS ==================== */}

      <Route
        path="/candidate/ai-analysis"
        element={<AIAnalysis />}
      />

      {/* Candidate Profile */}
      <Route
        path="/candidate/profile"
        element={<Profile />}
      />

      {/* Request HR Access */}
      <Route
        path="/request-hr-access"
        element={<RequestHRAccess />}
      />

      {/* Apply for Job */}
      <Route
        path="/candidate/apply/:jobId"
        element={<ApplyJob />}
      />

    </Routes>
  );
}