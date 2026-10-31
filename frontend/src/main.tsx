import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, RequireRole } from "./auth";
import Layout from "./components/Layout";
import { PRODUCT_NAME } from "./config";
import { CandidateApplication, CandidateDashboard, CandidateInterview } from "./pages/candidate/Candidate";
import { ApplicationsPage, HrDashboard } from "./pages/hr/HrJobs";
import { ApprovalsPage, CalendarPage, RubricPage } from "./pages/hr/HrOps";
import { ShortlistPage } from "./pages/hr/Shortlist";
import { JobDetailPage, JobsPage, LoginPage, RegisterPage } from "./pages/public/Public";
import { SupervisorPage } from "./pages/supervisor/Supervisor";
import "./styles.css";

document.title = PRODUCT_NAME;
const staff = ["recruiter", "supervisor"] as const;

function App() {
  return (
    <Routes>
      <Route element={<Layout area="public" />}>
        <Route path="/" element={<Navigate to="/jobs" replace />} />
        <Route path="/jobs" element={<JobsPage />} />
        <Route path="/jobs/:slug" element={<JobDetailPage />} />
        <Route path="/login" element={<LoginPage portal="candidate" />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/candidate" element={<RequireRole roles={["candidate"]} loginPath="/login"><CandidateDashboard /></RequireRole>} />
        <Route path="/candidate/applications/:id" element={<RequireRole roles={["candidate"]} loginPath="/login"><CandidateApplication /></RequireRole>} />
        <Route path="/candidate/interviews/:invitationId" element={<RequireRole roles={["candidate"]} loginPath="/login"><CandidateInterview /></RequireRole>} />
      </Route>
      <Route element={<Layout area="hr" />}>
        <Route path="/hr/login" element={<LoginPage portal="staff" />} />
        <Route path="/hr" element={<RequireRole roles={[...staff]} loginPath="/hr/login"><HrDashboard /></RequireRole>} />
        <Route path="/hr/jobs/:id/applications" element={<RequireRole roles={[...staff]} loginPath="/hr/login"><ApplicationsPage /></RequireRole>} />
        <Route path="/hr/jobs/:id/shortlist" element={<RequireRole roles={[...staff]} loginPath="/hr/login"><ShortlistPage /></RequireRole>} />
        <Route path="/hr/jobs/:id/rubric" element={<RequireRole roles={[...staff]} loginPath="/hr/login"><RubricPage /></RequireRole>} />
        <Route path="/hr/calendar" element={<RequireRole roles={[...staff]} loginPath="/hr/login"><CalendarPage /></RequireRole>} />
        <Route path="/hr/approvals" element={<RequireRole roles={[...staff]} loginPath="/hr/login"><ApprovalsPage /></RequireRole>} />
      </Route>
      <Route element={<Layout area="supervisor" />}>
        <Route path="/supervisor" element={<RequireRole roles={["supervisor"]} loginPath="/hr/login"><SupervisorPage /></RequireRole>} />
      </Route>
      <Route path="*" element={<div className="page"><h1>Page not found</h1><a href="/jobs">Go to open positions</a></div>} />
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
