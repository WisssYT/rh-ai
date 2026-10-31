import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import "@fontsource-variable/newsreader/opsz.css";
import "@fontsource-variable/newsreader/opsz-italic.css";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./styles/tokens.css";
import "./styles/candidate.css";
import "./styles/recruiter.css";
import { AuthProvider, RequireRole } from "./auth";
import CandidateLayout from "./components/CandidateLayout";
import RecruiterLayout from "./components/RecruiterLayout";
import { PRODUCT_NAME } from "./config";
import { CandidateApplication, CandidateDashboard, CandidateInterview, CandidateProfile } from "./pages/candidate/Candidate";
import { ApplicationsPage, HrDashboard } from "./pages/hr/HrJobs";
import { ApprovalsPage, CalendarPage, RubricPage } from "./pages/hr/HrOps";
import { ShortlistPage } from "./pages/hr/Shortlist";
import { JobDetailPage, JobsPage, LoginPage, RegisterPage, StaffLoginPage } from "./pages/public/Public";
import { SupervisorPage } from "./pages/supervisor/Supervisor";

document.title = PRODUCT_NAME;
const staff = ["recruiter", "supervisor"] as const;
const cand = (el: React.ReactNode) => <RequireRole roles={["candidate"]} loginPath="/login">{el}</RequireRole>;
const hr = (el: React.ReactNode) => <RequireRole roles={[...staff]} loginPath="/hr/login">{el}</RequireRole>;

function App() {
  return (
    <Routes>
      {/* Candidate site */}
      <Route element={<CandidateLayout />}>
        <Route path="/" element={<Navigate to="/jobs" replace />} />
        <Route path="/jobs" element={<JobsPage />} />
        <Route path="/jobs/:slug" element={<JobDetailPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/candidate" element={cand(<CandidateDashboard />)} />
        <Route path="/candidate/profile" element={cand(<CandidateProfile />)} />
        <Route path="/candidate/applications/:id" element={cand(<CandidateApplication />)} />
        <Route path="/candidate/interviews/:invitationId" element={cand(<CandidateInterview />)} />
      </Route>
      {/* Recruiter site */}
      <Route path="/hr/login" element={<StaffLoginPage />} />
      <Route element={hr(<RecruiterLayout />)}>
        <Route path="/hr" element={<HrDashboard />} />
        <Route path="/hr/jobs/:id/applications" element={<ApplicationsPage />} />
        <Route path="/hr/jobs/:id/shortlist" element={<ShortlistPage />} />
        <Route path="/hr/jobs/:id/rubric" element={<RubricPage />} />
        <Route path="/hr/calendar" element={<CalendarPage />} />
        <Route path="/hr/approvals" element={<ApprovalsPage />} />
        <Route path="/supervisor" element={<RequireRole roles={["supervisor"]} loginPath="/hr/login"><SupervisorPage /></RequireRole>} />
      </Route>
      <Route path="*" element={<div className="gate"><h1>Page not found</h1><a href="/jobs">Go to open roles</a></div>} />
    </Routes>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
