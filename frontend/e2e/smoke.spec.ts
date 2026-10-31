import { expect, test, type Page } from "@playwright/test";

// Main journey through the real UI and API. Requires: `python -m app.cli seed-demo` on a fresh DB,
// AI mode = replay, the worker running, and Mailpit on :8025.
const STAFF_PW = "DemoStaff!2026-local";
const CAND_PW = "DemoCandidate!2026";

async function login(page: Page, path: string, email: string, password: string) {
  await page.goto(path);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((u) => !u.pathname.endsWith("/login"));
}

test("candidate applies, HR analyses, approves shortlist and invitation, candidate books, HR confirms", async ({ browser }) => {
  // 1. Candidate submits a PDF
  const cand = await (await browser.newContext()).newPage();
  await login(cand, "/login", "demo.candidate@example.test", CAND_PW);
  await cand.goto("/jobs");
  await cand.getByRole("link", { name: /Backend Developer \(Python\)/ }).click();
  await cand.getByLabel(/CV \(PDF/).setInputFiles("e2e/fixtures/dana_cv.pdf");
  await cand.getByRole("checkbox").check();
  await cand.getByRole("button", { name: "Submit application" }).click();
  await expect(cand.getByText("Application submitted")).toBeVisible();
  await expect(cand.getByRole("img", { name: "matches your account" })).toBeVisible();

  // 2. Recruiter authorizes a replay analysis run for all unevaluated applications
  const hr = await (await browser.newContext()).newPage();
  hr.on("dialog", (d) => d.accept());
  await login(hr, "/hr/login", "recruiter@nordlicht.example.test", STAFF_PW);
  await expect(hr.getByRole("heading", { name: "Overview" })).toBeVisible();
  await hr.getByRole("complementary", { name: "Recruiting navigation" }).getByRole("link", { name: /Backend Developer \(Python\)/ }).click();
  await hr.getByRole("button", { name: /Select all not evaluated/ }).click();
  await hr.getByRole("button", { name: /Review & authorize analysis/ }).click();
  await expect(hr.getByText(/REPLAY \(synthetic, not an LLM\)/)).toBeVisible();
  await hr.getByRole("button", { name: "Authorize run" }).click();
  await expect(hr.getByText(/Analysis run\s*completed/)).toBeVisible({ timeout: 60_000 });

  // Evidence drawer shows quotations with page references
  await hr.getByRole("row", { name: /Amira Ben Salah/ }).getByRole("button", { name: "Evidence" }).click();
  await expect(hr.getByText(/p1 · p1-s\d+/).first()).toBeVisible();
  await hr.getByRole("button", { name: "Close panel" }).click();

  // 3. Shortlist: live weight preview (0 model calls), save draft, approve
  await hr.getByRole("link", { name: "Ranking & shortlist" }).click();
  await expect(hr.getByText(/0 model calls/)).toBeVisible();
  await hr.getByLabel(/Containers & deployment/).fill("40");
  await expect(hr.getByText("preview - not saved")).toBeVisible();
  await hr.getByRole("button", { name: "Discard preview" }).click();
  await hr.getByRole("button", { name: "Save selection as draft" }).click();
  await expect(hr.getByText(/awaits your approval/)).toBeVisible();
  await hr.getByRole("button", { name: /Approve shortlist r\d/ }).click();
  await expect(hr.getByText(/Shortlist approved/)).toBeVisible();

  // 4. Prepare template invitations, approve exactly one
  await hr.getByRole("button", { name: "Prepare drafts (template)" }).click();
  await expect(hr.getByText(/draft\(s\) prepared \(template\)\. Nothing has been sent/)).toBeVisible();
  await hr.goto("/hr/approvals");
  const card = hr.locator(".card", { hasText: "Invitation · Amira Ben Salah" });
  await expect(card.getByText("amira.bensalah@example.test")).toBeVisible();
  await card.getByRole("button", { name: "Approve & send this exact message" }).click();
  await expect.poll(async () => {
    const r = await hr.request.get("http://localhost:8025/api/v1/search?query=to:amira.bensalah@example.test");
    return (await r.json()).messages_count;
  }, { timeout: 30_000 }).toBeGreaterThan(0);

  // 5. Candidate opens the invitation (link from the email) and requests a slot
  const msgs = await (await hr.request.get("http://localhost:8025/api/v1/search?query=to:amira.bensalah@example.test")).json();
  const msg = await (await hr.request.get(`http://localhost:8025/api/v1/message/${msgs.messages[0].ID}`)).json();
  const link = (msg.Text as string).match(/http:\/\/localhost:5173\/candidate\/interviews\/[a-f0-9]+/)![0];
  const amira = await (await browser.newContext()).newPage();
  await amira.goto(link);
  await expect(amira).toHaveURL(/\/login\?next=/); // the link is not a login credential
  await amira.getByLabel("Email").fill("amira.bensalah@example.test");
  await amira.getByLabel("Password").fill(CAND_PW);
  await amira.getByRole("button", { name: "Sign in" }).click();
  await amira.waitForURL(/\/candidate\/interviews\//);
  await expect(amira.getByText(/Interview · Backend Developer/)).toBeVisible();
  await amira.locator(".slot-btn").first().click();
  await amira.getByRole("button", { name: "Request this time" }).click();
  await expect(amira.getByText(/Requested - awaiting HR confirmation/)).toBeVisible();

  // 6. HR confirms in the calendar -> finalized interview
  await hr.goto("/hr/calendar");
  const pending = hr.locator(".criterion", { hasText: "Amira Ben Salah" });
  await pending.getByRole("button", { name: "Confirm interview" }).click();
  await expect(hr.locator(".criterion", { hasText: "Amira Ben Salah" })).toHaveCount(0);
  await amira.reload();
  await expect(amira.getByText("Confirmed by the recruiter")).toBeVisible();
});
