# Interview invites onto the calendar

`interview-calendar-sync.gs` runs inside the job seeker's own Google account.
It reads only the emails that match its search query, asks Groq to pull out
the date, time and meeting link, and creates a Calendar event with a popup
reminder 30 minutes before and an email reminder the day before.

Running it in her account, rather than from our app, is what keeps this free:
no Google verification, no security assessment, no limits on how many people
use Job Seeker.

## Why Groq and not Gemini

The script sends the subject and body of a candidate email to a model. Groq's
terms say API inputs and outputs are not used to train models, and Zero Data
Retention can be switched on per account. Gemini's free tier allows Google to
use the content to improve its products, which is the wrong trade for someone
else's mail. The Gemini path is still in the file (`CONFIG.PROVIDER =
'gemini'`) if you ever want it, but Groq is the default and the same key the
Streamlit app already uses.

## Setup - about five minutes, once

Do this while signed in to the Google account whose mail should be scanned.

1. Open **script.google.com** and click **New project**.
2. Rename it (top left) to **Interview Calendar Sync**.
3. Delete whatever is in `Code.gs`, paste in the whole of
   `interview-calendar-sync.gs`, and press the save icon.
4. Click the gear (**Project Settings**) in the left sidebar. Scroll to
   **Script Properties**, click **Add script property**:
   - Property: `GROQ_API_KEY`
   - Value: the key from console.groq.com
   Click **Save script properties**.
5. Back in the editor (`< >` icon), pick **testRun** in the function dropdown
   and click **Run**. Google will ask for permission:
   - **Review permissions** -> choose the account
   - **Advanced** -> **Go to Interview Calendar Sync (unsafe)**
   - **Allow**

   The "unsafe" wording is what Google shows for any script that has not gone
   through its review; it is your own script, and the permissions are exactly
   the three it needs: read Gmail, create Calendar events, call an external
   API. Nobody else can run it.
6. Read the **Execution log** at the bottom. `testRun` creates nothing - it
   prints what it *would* create, so you can see it found the right emails.
7. Click the clock (**Triggers**) in the sidebar, then **Add Trigger**:
   - Function: `scanGmailForInterviews`
   - Deployment: `Head`
   - Event source: `Time-driven`
   - Type: `Minutes timer` -> `Every 30 minutes`
   Click **Save**.

That is the whole thing. From then on it runs by itself.

## What it does and does not do

- Reads only threads matching `CONFIG.SEARCH_QUERY` - interview wording, last
  three days, not already processed.
- Skips emails that only ask for availability, and job alerts and rejections.
- Labels handled threads `Interview-Processed` so nothing is done twice. If a
  parse fails, the thread is left unlabelled and the next run retries it.
- Checks the calendar before creating, so a follow-up reply does not produce a
  duplicate event.
- Never replies, never deletes, never moves mail.

## Checking on it later

- **Executions** in the sidebar shows every run and its log.
- To pause it, delete the trigger. To stop it entirely, delete the project.
- To widen or narrow what it reads, edit `CONFIG.SEARCH_QUERY`. It is ordinary
  Gmail search syntax.
