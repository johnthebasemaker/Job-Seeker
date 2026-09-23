/**
 * Rules test for the form filler. No browser, no dependencies:
 *
 *   node extension/tests/rules.test.js
 *
 * It covers the part most likely to be wrong - which saved answer a given
 * question gets - and the refusals that matter.
 */
"use strict";

const assert = require("node:assert");
const path = require("node:path");

const { norm, isYes, pickOption, valueFor, SENSITIVE } = require(
  path.join(__dirname, "..", "content", "fill.js")
);

const PACK = {
  profile: {
    full_name: "Priya Raman",
    email: "priya@example.com",
    phone: "+91 98765 43210",
    location: "Chennai",
    linkedin: "https://linkedin.com/in/priyaraman",
    github: "https://github.com/priya",
    website: "",
  },
  answers: {
    work_authorisation: "Yes, Indian citizen",
    visa_sponsorship: "No",
    total_experience: "3",
    relevant_experience: "2",
    current_salary: "6 LPA",
    expected_salary: "9 LPA",
    notice_period: "30 days",
    availability: "Immediately",
    relocation: "Yes, within India",
    highest_qualification: "B.E. Computer Science",
    languages: "English, Tamil",
    why_this_role: "I want to work on backend systems at scale.",
    custom: [{ q: "How did you hear about us?", a: "Through a friend" }],
  },
};

const JOB = { cover_note: "Short note about the role." };

let passed = 0;
function check(label, actual, expected) {
  assert.strictEqual(actual, expected, `${label}: got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)}`);
  passed += 1;
}

// --- straight profile fields
check("email", valueFor(norm("Email address *"), PACK, JOB).value, "priya@example.com");
check("phone", valueFor(norm("Mobile number"), PACK, JOB).value, "+91 98765 43210");
check("first name", valueFor(norm("First name"), PACK, JOB).value, "Priya");
check("last name", valueFor(norm("Last Name"), PACK, JOB).value, "Raman");
check("full name", valueFor(norm("Full Name"), PACK, JOB).value, "Priya Raman");
check("linkedin", valueFor(norm("LinkedIn Profile"), PACK, JOB).value, PACK.profile.linkedin);
check("city", valueFor(norm("Current City"), PACK, JOB).value, "Chennai");
// website falls back to github when there is no personal site
check("portfolio", valueFor(norm("Portfolio / website"), PACK, JOB).value, PACK.profile.github);

// --- the specific answer must beat the general one
check("expected salary", valueFor(norm("Expected CTC"), PACK, JOB).value, "9 LPA");
check("current salary", valueFor(norm("Current CTC"), PACK, JOB).value, "6 LPA");
check("relevant experience",
  valueFor(norm("Years of relevant experience"), PACK, JOB).value, "2");
check("total experience",
  valueFor(norm("Total years of experience"), PACK, JOB).value, "3");

// --- screening answers
check("notice", valueFor(norm("What is your notice period?"), PACK, JOB).value, "30 days");
check("authorisation",
  valueFor(norm("Are you legally authorized to work in India?"), PACK, JOB).value,
  "Yes, Indian citizen");
check("sponsorship",
  valueFor(norm("Will you now or in the future require sponsorship?"), PACK, JOB).value, "No");
check("relocation",
  valueFor(norm("Are you willing to relocate?"), PACK, JOB).value, "Yes, within India");
check("start date",
  valueFor(norm("When can you start?"), PACK, JOB).value, "Immediately");

// --- the job's cover note wins over the generic reason for looking
check("cover letter", valueFor(norm("Cover letter"), PACK, JOB).value, JOB.cover_note);
check("cover letter without a note",
  valueFor(norm("Why do you want this job?"), PACK, {}).value, PACK.answers.why_this_role);

// --- the user's own question and answer pairs
check("custom answer",
  valueFor(norm("How did you hear about us?"), PACK, JOB).value, "Through a friend");

// --- nothing is invented
check("unknown question", valueFor(norm("Describe a conflict you resolved"), PACK, JOB).value, null);
check("no answer saved",
  valueFor(norm("Expected CTC"), { profile: {}, answers: {} }, JOB).value, null);

// --- refusals
for (const question of [
  "Gender", "What is your race / ethnicity?", "Are you a protected veteran?",
  "Do you have a disability?", "Date of birth", "Aadhaar number", "Marital status",
]) {
  assert.ok(SENSITIVE.test(norm(question)), `should refuse: ${question}`);
  passed += 1;
}
assert.ok(!SENSITIVE.test(norm("Expected salary")), "salary is not a demographic question");
passed += 1;

// --- option picking for radios and selects
const options = ["Yes", "No"];
const text = (option) => norm(option);
check("yes/no from a sentence", pickOption(options, "Yes, Indian citizen", text), "Yes");
check("plain no", pickOption(options, "No", text), "No");
check("notice period dropdown",
  pickOption(["Immediate", "15 days", "30 days", "60 days"], "30 days", text), "30 days");
check("no match returns null", pickOption(["Maybe"], "Definitely", text), null);
assert.ok(isYes("yes, absolutely"), "isYes should read a leading yes");

console.log(`rules.test.js: ${passed} checks passed`);
