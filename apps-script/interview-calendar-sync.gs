/**
 * Interview Calendar Sync - Job Seeker
 *
 * Watches Gmail for interview invitations, pulls out the date, time and
 * meeting link, and puts them on Google Calendar with reminders.
 *
 * It runs inside the user's own Google account, so there is no OAuth
 * verification to do and nothing to pay for. Google asks for permission once,
 * from the person who owns the mailbox.
 *
 * Privacy: the subject and body of a candidate email are sent to Groq to be
 * parsed. Groq's terms say API inputs are not used to train models, and Zero
 * Data Retention can be switched on in the Groq console under Settings ->
 * Data Controls. Turn it on. Nothing is sent anywhere else, and emails that
 * do not match the search query are never read.
 *
 * Setup lives in apps-script/README.md. In short: paste this into
 * script.google.com, add GROQ_API_KEY under Project Settings -> Script
 * Properties, run testRun once to authorise, then add a time trigger for
 * scanGmailForInterviews.
 */

const CONFIG = {
  // Only these threads are ever read.
  SEARCH_QUERY:
    'newer_than:3d -label:Interview-Processed -in:chats ' +
    '("interview" OR "screening call" OR "technical round" OR "hiring manager" ' +
    'OR "interview confirmation" OR "invitation to interview")',
  PROCESSED_LABEL: 'Interview-Processed',
  MAX_THREADS: 10,

  // Groq keeps this in line with the rest of Job Seeker: no training on your data.
  PROVIDER: 'groq',
  GROQ_MODEL: 'openai/gpt-oss-120b',
  GEMINI_MODEL: 'gemini-2.0-flash',

  DEFAULT_MINUTES: 45,
  POPUP_REMINDER_MINUTES: 30,
  EMAIL_REMINDER_MINUTES: 60 * 24,
  MAX_BODY_CHARS: 6000
};

/** The function the time trigger calls. */
function scanGmailForInterviews() {
  processInbox(false);
}

/** Run this by hand first: it reports what it would do and creates nothing. */
function testRun() {
  processInbox(true);
}

function processInbox(dryRun) {
  const apiKey = getApiKey_();
  const label = getOrCreateLabel_(CONFIG.PROCESSED_LABEL);
  const calendar = CalendarApp.getDefaultCalendar();
  const timeZone = Session.getScriptTimeZone();

  const threads = GmailApp.search(CONFIG.SEARCH_QUERY, 0, CONFIG.MAX_THREADS);
  Logger.log(`${threads.length} thread(s) to look at${dryRun ? ' (dry run)' : ''}`);

  threads.forEach(function (thread) {
    const messages = thread.getMessages();
    const message = messages[messages.length - 1];
    const subject = message.getSubject();
    const sender = message.getFrom();
    const body = message.getPlainBody().slice(0, CONFIG.MAX_BODY_CHARS);

    let details;
    try {
      details = extractInterviewDetails_(subject, sender, body, timeZone, apiKey);
    } catch (error) {
      // A transient failure must not silently swallow an invitation, so the
      // thread stays unlabelled and the next run tries again.
      Logger.log(`Could not parse "${subject}": ${error.message}. Will retry.`);
      return;
    }

    if (!details || !details.isScheduledInterview) {
      Logger.log(`Not a scheduled interview: "${subject}"`);
      if (!dryRun) thread.addLabel(label);
      return;
    }

    const start = new Date(details.startTime);
    let end = details.endTime ? new Date(details.endTime) : null;
    if (isNaN(start.getTime())) {
      Logger.log(`Unusable start time in "${subject}". Leaving it for you.`);
      return;
    }
    if (!end || isNaN(end.getTime()) || end <= start) {
      end = new Date(start.getTime() + CONFIG.DEFAULT_MINUTES * 60000);
    }

    const title = details.eventTitle || `Interview - ${subject}`;
    if (eventAlreadyExists_(calendar, title, start)) {
      Logger.log(`Already on the calendar: "${title}"`);
      if (!dryRun) thread.addLabel(label);
      return;
    }

    const description = [
      `From: ${sender}`,
      details.meetingLink ? `Link: ${details.meetingLink}` : '',
      '',
      details.notes || '',
      '',
      `Email subject: ${subject}`,
      `Added by Job Seeker on ${new Date().toDateString()}`
    ].filter(String).join('\n');

    if (dryRun) {
      Logger.log(`WOULD CREATE: "${title}" on ${start} (${details.meetingLink || 'no link'})`);
      return;
    }

    const event = calendar.createEvent(title, start, end, {
      location: details.meetingLink || '',
      description: description
    });
    event.addPopupReminder(CONFIG.POPUP_REMINDER_MINUTES);
    event.addEmailReminder(CONFIG.EMAIL_REMINDER_MINUTES);
    thread.addLabel(label);
    Logger.log(`Created "${title}" on ${start}`);
  });
}

// --------------------------------------------------------------- helpers
function getApiKey_() {
  const properties = PropertiesService.getScriptProperties();
  const key =
    CONFIG.PROVIDER === 'gemini'
      ? properties.getProperty('GEMINI_API_KEY')
      : properties.getProperty('GROQ_API_KEY');
  if (!key) {
    throw new Error(
      `No API key. Open Project Settings -> Script Properties and add ` +
      `${CONFIG.PROVIDER === 'gemini' ? 'GEMINI_API_KEY' : 'GROQ_API_KEY'}.`
    );
  }
  return key;
}

function getOrCreateLabel_(name) {
  return GmailApp.getUserLabelByName(name) || GmailApp.createLabel(name);
}

/** Guards against a second event when a thread gets a follow-up reply. */
function eventAlreadyExists_(calendar, title, start) {
  const from = new Date(start.getTime() - 60 * 60000);
  const to = new Date(start.getTime() + 60 * 60000);
  return calendar.getEvents(from, to).some(function (event) {
    return event.getTitle() === title;
  });
}

function buildPrompt_(subject, sender, body, timeZone) {
  return [
    'You read interview emails and return calendar details.',
    `Current time: ${new Date().toISOString()}`,
    `The reader is in timezone: ${timeZone}`,
    '',
    `Subject: ${subject}`,
    `From: ${sender}`,
    'Body:',
    body,
    '',
    'Decide whether this email CONFIRMS an interview at a specific date and time.',
    'If it only asks for availability, or offers slots to choose from, or is a',
    'job alert, a newsletter or a rejection, then isScheduledInterview is false.',
    '',
    'Return JSON only, with exactly these keys:',
    '{"isScheduledInterview": boolean,',
    ' "eventTitle": "Interview - <company or interviewer>",',
    ' "startTime": "ISO 8601 with timezone offset",',
    ' "endTime": "ISO 8601 with timezone offset, 45 minutes after start if not stated",',
    ' "meetingLink": "the Meet/Zoom/Teams URL, or an empty string",',
    ' "notes": "one or two lines: round, interviewers, what to prepare"}'
  ].join('\n');
}

function extractInterviewDetails_(subject, sender, body, timeZone, apiKey) {
  const prompt = buildPrompt_(subject, sender, body, timeZone);
  const raw =
    CONFIG.PROVIDER === 'gemini'
      ? callGemini_(prompt, apiKey)
      : callGroq_(prompt, apiKey);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (error) {
    const start = raw.indexOf('{');
    const end = raw.lastIndexOf('}');
    if (start !== -1 && end > start) return JSON.parse(raw.slice(start, end + 1));
    throw new Error('the model did not return JSON');
  }
}

function callGroq_(prompt, apiKey) {
  const response = UrlFetchApp.fetch('https://api.groq.com/openai/v1/chat/completions', {
    method: 'post',
    contentType: 'application/json',
    headers: { Authorization: `Bearer ${apiKey}` },
    muteHttpExceptions: true,
    payload: JSON.stringify({
      model: CONFIG.GROQ_MODEL,
      messages: [
        { role: 'system', content: 'You reply with JSON and nothing else.' },
        { role: 'user', content: prompt }
      ],
      temperature: 0.1,
      max_tokens: 1200,
      reasoning_effort: 'low',
      response_format: { type: 'json_object' }
    })
  });
  const code = response.getResponseCode();
  if (code !== 200) {
    throw new Error(`Groq returned ${code}: ${response.getContentText().slice(0, 200)}`);
  }
  return JSON.parse(response.getContentText()).choices[0].message.content;
}

function callGemini_(prompt, apiKey) {
  const url =
    `https://generativelanguage.googleapis.com/v1beta/models/${CONFIG.GEMINI_MODEL}` +
    `:generateContent?key=${apiKey}`;
  const response = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    muteHttpExceptions: true,
    payload: JSON.stringify({
      contents: [{ parts: [{ text: prompt }] }],
      generationConfig: { responseMimeType: 'application/json', temperature: 0.1 }
    })
  });
  const code = response.getResponseCode();
  if (code !== 200) {
    throw new Error(`Gemini returned ${code}: ${response.getContentText().slice(0, 200)}`);
  }
  return JSON.parse(response.getContentText()).candidates[0].content.parts[0].text;
}
