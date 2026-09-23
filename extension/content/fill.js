/**
 * Job Seeker Helper - form filler.
 *
 * Fills an application form from the pack the user imported, then stops.
 * Three rules are enforced here, not just documented:
 *
 *   1. It never clicks Submit, Apply, Continue or anything like it.
 *   2. It never answers a question the pack has no answer for. Those are
 *      listed for the person instead.
 *   3. It never touches demographic questions (gender, race, disability,
 *      veteran status, date of birth), passwords, or payment fields.
 */
(() => {
  "use strict";

  // Under Node (the rules test) there is no DOM; only the pure matching
  // helpers are exported and nothing below touches the page.
  const inBrowser = typeof window !== "undefined" && typeof document !== "undefined";
  if (inBrowser) {
    if (window.__jobSeekerHelperLoaded) return;
    window.__jobSeekerHelperLoaded = true;
  }

  const PANEL_ID = "job-seeker-helper-panel";

  // ------------------------------------------------------------------ text
  const norm = (value) =>
    (value || "")
      .toString()
      .toLowerCase()
      .replace(/[‘’]/g, "'")
      .replace(/[*:?•·]/g, " ")
      .replace(/\s+/g, " ")
      .trim();

  const isYes = (value) => /^\s*(yes|y|true|authorised|authorized)\b/i.test(value || "");
  const isNo = (value) => /^\s*(no|n|false|not)\b/i.test(value || "");

  /** Everything that might name a field, most trustworthy first. */
  function labelText(el) {
    const parts = [];
    const push = (text) => {
      const clean = norm(text);
      if (clean && !parts.includes(clean)) parts.push(clean);
    };

    push(el.getAttribute("aria-label"));

    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) {
      labelledBy.split(/\s+/).forEach((id) => push(document.getElementById(id)?.textContent));
    }
    if (el.id) {
      document.querySelectorAll(`label[for="${CSS.escape(el.id)}"]`).forEach((l) =>
        push(l.textContent)
      );
    }
    push(el.closest("label")?.textContent);

    // The question text on ATS forms usually sits in a wrapper above the input.
    let node = el.parentElement;
    for (let depth = 0; node && depth < 4; depth += 1, node = node.parentElement) {
      const legend = node.querySelector(":scope > legend, :scope > .legend");
      if (legend) push(legend.textContent);
      const heading = node.querySelector(
        ":scope > label, :scope > .label, :scope > h2, :scope > h3, :scope > h4, :scope > p, :scope > span"
      );
      if (heading && heading.textContent && heading.textContent.length < 200) {
        push(heading.textContent);
      }
    }

    push(el.getAttribute("placeholder"));
    push(el.getAttribute("name"));
    push(el.id);
    return parts.join(" | ");
  }

  // --------------------------------------------------------------- setting
  /** React and Angular ignore a plain `el.value = x`, so use the native setter. */
  function setValue(el, value) {
    const proto =
      el instanceof HTMLTextAreaElement
        ? window.HTMLTextAreaElement.prototype
        : window.HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
    if (setter) setter.call(el, value);
    else el.value = value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.dispatchEvent(new Event("blur", { bubbles: true }));
  }

  function optionText(option) {
    return norm(option.textContent || option.value);
  }

  function pickOption(candidates, desired, getText) {
    const want = norm(desired);
    if (!want) return null;
    const wantYes = isYes(want);
    const wantNo = isNo(want);

    const exact = candidates.find((c) => getText(c) === want);
    if (exact) return exact;

    if (wantYes || wantNo) {
      const target = wantYes ? /^yes\b/ : /^no\b/;
      const hit = candidates.find((c) => target.test(getText(c)));
      if (hit) return hit;
    }
    return (
      candidates.find((c) => getText(c) && want.includes(getText(c))) ||
      candidates.find((c) => getText(c).includes(want)) ||
      null
    );
  }

  function setSelect(el, desired) {
    const options = Array.from(el.options).filter((o) => o.value !== "");
    const chosen = pickOption(options, desired, optionText);
    if (!chosen) return false;
    el.value = chosen.value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

  function setRadioGroup(radios, desired) {
    const chosen = pickOption(radios, desired, (radio) => norm(labelText(radio)).split(" | ")[0]);
    if (!chosen) return false;
    chosen.click();
    return true;
  }

  /** Turn the base64 resume into a real File and drop it on the input. */
  function attachFile(input, base64, filename) {
    try {
      const binary = atob(base64);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
      const file = new File([bytes], filename, { type: "application/pdf" });
      const transfer = new DataTransfer();
      transfer.items.add(file);
      input.files = transfer.files;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    } catch (error) {
      console.warn("[Job Seeker] could not attach the resume", error);
      return false;
    }
  }

  // ----------------------------------------------------------------- rules
  /** Questions we refuse to answer automatically. */
  const SENSITIVE =
    /(gender|sex\b|race|ethnic|hispanic|latino|veteran|disab|date of birth|dob\b|\bage\b|marital|religion|caste|sexual orientation|aadhaar|aadhar|pan number|passport number|social security|ssn\b)/;

  const RULES = [
    { id: "first_name", test: /\bfirst name\b|\bgiven name\b/, get: (p) => (p.full_name || "").split(" ")[0] },
    {
      id: "last_name",
      test: /\blast name\b|\bsurname\b|\bfamily name\b/,
      get: (p) => (p.full_name || "").split(" ").slice(1).join(" "),
    },
    { id: "full_name", test: /\b(full name|your name|name)\b/, get: (p) => p.full_name },
    { id: "email", test: /e-?mail/, get: (p) => p.email },
    { id: "phone", test: /phone|mobile|contact number|whatsapp/, get: (p) => p.phone },
    { id: "linkedin", test: /linked ?in/, get: (p) => p.linkedin },
    { id: "github", test: /git ?hub/, get: (p) => p.github },
    {
      id: "website",
      test: /portfolio|personal (web)?site|website|blog/,
      get: (p) => p.website || p.github,
    },
    {
      id: "location",
      test: /current (city|location)|city|location|where are you based|address/,
      get: (p) => p.location,
    },

    { id: "notice_period", test: /notice period/, get: (p, a) => a.notice_period },
    {
      id: "expected_salary",
      test: /expected (salary|ctc|compensation)|salary expectation|desired salary/,
      get: (p, a) => a.expected_salary,
    },
    {
      id: "current_salary",
      test: /current (salary|ctc|compensation)|present ctc/,
      get: (p, a) => a.current_salary,
    },
    {
      id: "relevant_experience",
      test: /relevant experience|experience in this|years of relevant/,
      get: (p, a) => a.relevant_experience,
    },
    {
      id: "total_experience",
      test: /total experience|years of experience|work experience|how many years/,
      get: (p, a) => a.total_experience,
    },
    {
      id: "work_authorisation",
      test: /author(ized|ised) to work|right to work|legally (able|entitled) to work|work permit/,
      get: (p, a) => a.work_authorisation,
    },
    {
      id: "visa_sponsorship",
      test: /sponsorship|require (a )?visa|need sponsorship/,
      get: (p, a) => a.visa_sponsorship,
    },
    { id: "relocation", test: /relocat/, get: (p, a) => a.relocation },
    {
      id: "availability",
      test: /available to start|start date|when can you (join|start)|availability|joining date/,
      get: (p, a) => a.availability,
    },
    {
      id: "highest_qualification",
      test: /highest (qualification|education|degree)|qualification|degree/,
      get: (p, a) => a.highest_qualification,
    },
    { id: "languages", test: /languages?( known| spoken)?/, get: (p, a) => a.languages },
    {
      id: "cover_letter",
      test: /cover letter|why (do you want|are you interested)|motivation|tell us about yourself|additional information/,
      get: (p, a, job) => job?.cover_note || a.why_this_role,
    },
  ];

  function customAnswer(label, answers) {
    const list = Array.isArray(answers.custom) ? answers.custom : [];
    const want = norm(label);
    for (const pair of list) {
      const question = norm(pair.q);
      if (question && (want.includes(question) || question.includes(want))) return pair.a;
    }
    return null;
  }

  function valueFor(label, pack, job) {
    const profile = pack.profile || {};
    const answers = pack.answers || {};
    const custom = customAnswer(label, answers);
    if (custom) return { value: custom, rule: "your own answer" };
    for (const rule of RULES) {
      if (rule.test.test(label)) {
        const value = rule.get(profile, answers, job);
        if (value) return { value: String(value), rule: rule.id };
        return { value: null, rule: rule.id };
      }
    }
    return { value: null, rule: null };
  }

  // ------------------------------------------------------------------ fill
  function fillableFields() {
    return Array.from(document.querySelectorAll("input, select, textarea")).filter((el) => {
      if (el.disabled || el.readOnly) return false;
      if (el.type === "hidden" || el.type === "password" || el.type === "submit") return false;
      if (el.offsetParent === null && el.type !== "file") return false;
      return true;
    });
  }

  function fillForm(pack, job) {
    const report = { filled: [], needsYou: [], skipped: [], resume: null };
    const seenRadioGroups = new Set();

    for (const el of fillableFields()) {
      const label = labelText(el);

      if (el.type === "file") {
        if (job && job.resume_pdf_b64 && /resume|cv|upload/.test(label + " " + norm(el.name))) {
          const ok = attachFile(el, job.resume_pdf_b64, job.resume_filename || "resume.pdf");
          report.resume = ok ? job.resume_filename : null;
          if (!ok) report.needsYou.push({ label: "Resume upload", why: "attach it by hand" });
        }
        continue;
      }

      if (SENSITIVE.test(label)) {
        report.skipped.push({ label: shorten(label), why: "personal question - yours to answer" });
        continue;
      }

      if (el.type === "radio") {
        const name = el.name;
        if (!name || seenRadioGroups.has(name)) continue;
        seenRadioGroups.add(name);
        const group = Array.from(document.querySelectorAll(`input[type=radio][name="${CSS.escape(name)}"]`));
        const groupLabel = labelText(group[0]) + " " + labelText(el.closest("fieldset") || el);
        if (SENSITIVE.test(groupLabel)) {
          report.skipped.push({ label: shorten(groupLabel), why: "personal question" });
          continue;
        }
        const { value } = valueFor(groupLabel, pack, job);
        if (!value) {
          report.needsYou.push({ label: shorten(groupLabel), why: "no saved answer" });
          highlight(group[0]);
        } else if (setRadioGroup(group, value)) {
          report.filled.push({ label: shorten(groupLabel), value });
        } else {
          report.needsYou.push({ label: shorten(groupLabel), why: `no option matches "${value}"` });
          highlight(group[0]);
        }
        continue;
      }

      if (el.type === "checkbox") continue; // consents are the person's to give

      if (el.value && el.value.trim() !== "") continue; // never overwrite

      const { value } = valueFor(label, pack, job);
      if (!value) {
        if (el.required || /\*/.test(el.getAttribute("aria-label") || "")) {
          report.needsYou.push({ label: shorten(label), why: "no saved answer" });
          highlight(el);
        }
        continue;
      }

      if (el.tagName === "SELECT") {
        if (setSelect(el, value)) report.filled.push({ label: shorten(label), value });
        else {
          report.needsYou.push({ label: shorten(label), why: `no option matches "${value}"` });
          highlight(el);
        }
      } else {
        setValue(el, value);
        report.filled.push({ label: shorten(label), value });
      }
    }

    return report;
  }

  function shorten(label) {
    const first = (label || "").split(" | ")[0] || label || "this field";
    return first.length > 70 ? `${first.slice(0, 67)}...` : first;
  }

  function highlight(el) {
    el.style.outline = "2px solid #f59e0b";
    el.style.outlineOffset = "1px";
  }

  // ----------------------------------------------------------------- panel
  function buildPanel() {
    const host = document.createElement("div");
    host.id = PANEL_ID;
    host.style.cssText = "position:fixed;z-index:2147483647;right:16px;bottom:16px;";
    const shadow = host.attachShadow({ mode: "open" });
    shadow.innerHTML = `
      <style>
        .card{font:13px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;width:290px;
              background:#fff;color:#111;border:1px solid #d4d4d8;border-radius:12px;
              box-shadow:0 10px 30px rgba(0,0,0,.18);overflow:hidden}
        header{display:flex;align-items:center;gap:8px;padding:10px 12px;background:#2563eb;color:#fff}
        header strong{font-size:13px;font-weight:600;flex:1}
        header button{background:transparent;border:0;color:#fff;cursor:pointer;font-size:16px;line-height:1}
        .body{padding:12px;max-height:46vh;overflow:auto}
        .job{font-weight:600;margin-bottom:2px}
        .muted{color:#52525b;font-size:12px}
        button.action{width:100%;padding:9px 10px;border-radius:8px;border:0;background:#2563eb;
              color:#fff;font-weight:600;cursor:pointer;margin-top:10px}
        button.action:disabled{background:#a1a1aa;cursor:default}
        ul{margin:8px 0 0;padding-left:16px}
        li{margin:2px 0}
        .ok{color:#15803d}
        .warn{color:#b45309}
        .foot{padding:8px 12px;border-top:1px solid #e4e4e7;font-size:11px;color:#52525b}
      </style>
      <div class="card">
        <header><strong>Job Seeker Helper</strong><button id="close" title="Hide">×</button></header>
        <div class="body" id="body"></div>
        <div class="foot">It never presses Submit. Read the form, then send it yourself.</div>
      </div>`;
    shadow.getElementById("close").addEventListener("click", () => host.remove());
    document.documentElement.appendChild(host);
    return shadow;
  }

  function renderPanel(shadow, pack, job, report) {
    const body = shadow.getElementById("body");
    if (!pack) {
      body.innerHTML = `<div class="muted">No apply pack imported yet. Open the extension
        and import the file you downloaded from Job Seeker.</div>`;
      return;
    }
    const heading = job
      ? `<div class="job">${escapeHtml(job.title || "This application")}</div>
         <div class="muted">${escapeHtml(job.company || "")}</div>`
      : `<div class="job">No job selected</div>
         <div class="muted">Pick one in the extension popup to attach the right resume.</div>`;

    let result = "";
    if (report) {
      const items = [];
      if (report.resume) items.push(`<li class="ok">Attached ${escapeHtml(report.resume)}</li>`);
      items.push(`<li class="ok">Filled ${report.filled.length} field${report.filled.length === 1 ? "" : "s"}</li>`);
      report.needsYou.forEach((item) =>
        items.push(`<li class="warn">${escapeHtml(item.label)} - ${escapeHtml(item.why)}</li>`)
      );
      report.skipped.forEach((item) =>
        items.push(`<li class="muted">${escapeHtml(item.label)} - ${escapeHtml(item.why)}</li>`)
      );
      result = `<ul>${items.join("")}</ul>`;
    }

    body.innerHTML = `${heading}${result}`;
    const button = document.createElement("button");
    button.className = "action";
    button.textContent = report ? "Fill again" : "Fill this form";
    button.addEventListener("click", async () => {
      button.disabled = true;
      button.textContent = "Filling...";
      const fresh = fillForm(pack, job);
      renderPanel(shadow, pack, job, fresh);
    });
    body.appendChild(button);
  }

  function escapeHtml(value) {
    return (value || "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }

  // ------------------------------------------------------------------ boot
  function looksLikeAForm() {
    return fillableFields().length >= 3;
  }

  function matchJob(pack, activeJobId) {
    const jobs = pack.jobs || [];
    if (activeJobId) {
      const chosen = jobs.find((job) => job.id === activeJobId);
      if (chosen) return chosen;
    }
    const here = location.href.split("?")[0];
    return (
      jobs.find((job) => job.apply_url && here.startsWith(job.apply_url.split("?")[0])) ||
      jobs.find((job) => {
        try {
          return job.apply_url && new URL(job.apply_url).pathname === location.pathname;
        } catch (error) {
          return false;
        }
      }) ||
      null
    );
  }

  async function start() {
    if (!looksLikeAForm()) return;
    if (document.getElementById(PANEL_ID)) return;
    const stored = await chrome.storage.local.get(["pack", "activeJobId"]);
    const pack = stored.pack || null;
    if (!pack) return; // stay out of the way until there is something to fill
    const shadow = buildPanel();
    renderPanel(shadow, pack, matchJob(pack, stored.activeJobId), null);
  }

  if (!inBrowser) {
    // Exported for extension/tests/rules.test.js
    module.exports = { norm, isYes, isNo, pickOption, valueFor, customAnswer, SENSITIVE, RULES };
    return;
  }

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message?.type === "jobseeker:show") {
      document.getElementById(PANEL_ID)?.remove();
      start().then(() => sendResponse({ ok: true }));
      return true;
    }
    return false;
  });

  // Application forms are single-page apps: watch for the next step loading.
  let debounce;
  new MutationObserver(() => {
    clearTimeout(debounce);
    debounce = setTimeout(start, 700);
  }).observe(document.documentElement, { childList: true, subtree: true });

  start();
})();
