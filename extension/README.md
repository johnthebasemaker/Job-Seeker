# Job Seeker Helper (Chrome extension)

Fills an application form from the pack you downloaded in the app, then gets
out of the way. **It never clicks Submit.** You read what it filled, fix
anything it got wrong, answer whatever it left blank, and send it yourself.

Works in Chrome, Edge and Brave on a laptop. Chrome on Android cannot run
extensions at all, so on a phone use the PDF download and fill the form by
hand.

## Install it (about two minutes, once)

1. In Job Seeker, open **Apply** and click **Download the helper (.zip)**.
2. Unzip it. You get a folder called `extension`.
3. Open a new tab and go to `chrome://extensions`.
4. Turn on **Developer mode** with the switch in the top right.
5. Click **Load unpacked** and choose the `extension` folder - the one with
   `manifest.json` inside it, not the zip.
6. Click the puzzle-piece icon in the toolbar and pin **Job Seeker Helper** so
   it is always visible.

Keep the folder where it is. Chrome loads the extension from that path every
time it starts, so deleting the folder uninstalls it.

## Use it

1. In Job Seeker, mark the jobs you want as **ready**, open **Apply**, and
   click **Download apply pack**.
2. Click the helper icon, choose **Import apply pack**, and pick the file.
3. Press **Open and use** next to a job. The application page opens.
4. On that page a small panel appears in the bottom right. Press **Fill this
   form**.
5. The panel then tells you three things:
   - what it filled,
   - what it could not answer (those fields get an orange outline),
   - what it deliberately left alone.
6. Check everything, complete the rest, and press the site's own Submit.

The resume PDF is attached automatically wherever the form has a file upload.

## What it refuses to do

- **Submit.** Nothing in the code clicks a submit, apply or continue button,
  and there is a test that fails if that ever changes.
- **Guess.** A question with no saved answer is listed for you, never filled
  with something plausible.
- **Answer personal questions.** Gender, race, disability, veteran status,
  date of birth, marital status, ID numbers - it skips all of them and says
  so. Those are yours to answer or to leave blank.
- **Tick boxes for you.** Consent and declaration checkboxes are left alone.
- **Phone home.** It has no network permission. Everything it knows came from
  the file you imported, and it stays in this browser.

## When it does not fill much

- **Nothing happens on the page.** The panel only appears on Indeed,
  Greenhouse, Lever and Ashby. Elsewhere, fill the form yourself.
- **The panel says no pack.** Import the file again; a browser profile reset
  clears it.
- **Fields stay empty.** Some forms rename their questions oddly. Add the
  question and your answer under **Profile -> Application answers** in the
  app ("Your own questions and answers"), rebuild the pack, and it will match
  next time.
- **A multi-step Indeed form.** Press **Fill this form** again on each step.

## Remove your data

Click the helper icon and press **Delete the pack from this browser**. That
wipes the resumes and answers it was holding. Delete the downloaded
`job-seeker-pack.json` too - it contains your contact details.

## For developers

```bash
node extension/tests/rules.test.js   # which answer each question gets
```

`content/fill.js` holds the label matching and the safety rules; the same file
exports its pure helpers to Node for that test. Field mapping lives in
`RULES`, refusals in `SENSITIVE`.
