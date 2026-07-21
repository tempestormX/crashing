# Equilibrium — real-action demo script

**Target:** 2 minutes 35 seconds to 2 minutes 50 seconds.
**Recording rule:** every product claim must be shown by a real click, typed
input, saved result, reset, or logout. Do not use generic slides except for the
five-second title and final credits.

## What this demo may truthfully claim today

Show these as live actions:

- Anu's synthetic account can log in and log out.
- A typing trial happens inside Equilibrium and only aggregate timing metrics
  are presented to the student; the trial text is discarded.
- The student can view/reset their local interaction baseline and manage local
  data controls.
- The Focus area offers student-selected coping/reset options and a
  student-triggered, same-device notification test.
- The Reflection screen makes the AI opt-in explicit before a reflection can
  be sent, and transparently reports when live API access is unavailable.
- The Support screen opens/directs students to official Singapore university
  and national help routes; Equilibrium does not auto-refer anyone.

Do **not** describe the immediate test nudge as FCM or a stress-triggered
notification. It is a same-browser system notification requested by the
student. Do **not** claim that live FCM delivery, Supabase sync, hosted
reflection, counsellor referral, or external summary sharing are active unless
you have just verified the corresponding live integration status.

## Before recording

1. Start at the deployed Equilibrium URL in a browser window. Use 125% zoom;
   hide bookmarks, notifications and unrelated tabs.
2. Use only `anu@equilibrium.student`, the synthetic account.
3. In the typing trial, type this exact safe text manually (not pasted):
   `For this demo, I will break one study task into three small next steps.`
4. Keep your mouse cursor visible. Pause for one second after each click.
5. Record screen and microphone together in QuickTime, Zoom, OBS, or the
   macOS Screenshot toolbar. A live cursor is more persuasive than a montage.

## Time-coded live recording script

| Time | Live action to record | Voice-over |
| --- | --- | --- |
| 0:00–0:10 | Show the live URL and Equilibrium login screen. Move the cursor to Anu's account. | “University work can become overwhelming quickly. I built Equilibrium as a privacy-first study companion that helps students notice their own work rhythm and choose a small next step—without diagnosing them.” |
| 0:10–0:27 | Type Anu's password, click **Continue as Anu**, and wait for the real dashboard. | “This is Anu, a fictional test account. The first working flow is authentication: a student signs in to their own space, where the interface makes privacy controls and logout visible.” |
| 0:27–0:58 | Open **Privacy** → click **Start private trial** → manually type the synthetic sentence. Point at timing metrics and the statement that no text/keys/URLs are saved. Do not paste. | “Here is the core data-driven feature. The student voluntarily types inside this private trial. Equilibrium measures aggregate timing features such as pace, pauses and corrections. It does not store the typed sentence, individual keys, screenshots, tabs or browsing history.” |
| 0:58–1:15 | Save the private trial if timing events appear; otherwise show the metrics and click **Discard**. Return to the local baseline section. | “The point is a personal baseline, not a universal stress score. A student can inspect what was measured, discard the trial, reset the local baseline, or delete local data. The student stays in control.” |
| 1:15–1:38 | Open **Focus**, click one real reset option such as **Downshift** or **Step outside**, then open **Schedule a gentle nudge**. Click **Send a test notification now** and capture the system notification on this device. | “Equilibrium turns a pattern into an option, not an instruction. Anu chooses a coping tool, then explicitly requests this test nudge on her own device. A signal alone does not send a notification, and the usual schedule can still be postponed or declined.” |
| 1:38–1:58 | Open **Reflect**. Type a short synthetic reflection, choose a lens, visibly tick the AI consent checkbox, then click **Ask for a reflection**. Capture either the live response or the transparent unavailable screen. | “Private reflection is also opt-in. Before text can go to an assistant, the student must explicitly agree. In this hosted demo the live assistant may report that funded OpenAI API access is unavailable; Equilibrium then confirms that the reflection was not saved. Reflection content is never used to calculate capacity.” |
| 1:58–2:15 | Open **Support**. Scroll/cursor-point to NUS, NTU, SMU, SOS and mindline routes. Do not call or open crisis links during the recording. | “For real-world help, the app gives students direct access to Singapore campus and national support routes. It does not diagnose, book appointments or contact a counsellor automatically.” |
| 2:15–2:35 | Return to **Privacy** or **How it works**. Click **Log out** at the end. | “I developed the prototype with Codex, using GPT-5.6 to refine the student flow, build the local-first API and privacy controls, create the cadence-trial workflow, and prepare guarded integrations for Supabase, Firebase and approval-gated actions. Those integrations are deliberately separated from the core demo until live credentials and consent are verified.” |
| 2:35–2:47 | Show the logged-out screen, then briefly show a plain final title card. | “Equilibrium is designed around agency: no raw typing text, no scroll histories, no reflection text, and no automatic referrals. Students keep their momentum without giving up control.” |

## Five-second opening title card

Use this only before the real screen recording:

```text
EQUILIBRIUM
Private study support, on your terms
```

## Five-second closing title card

```text
Built with Codex and GPT-5.6
Live prototype · synthetic demo account only
```

## YouTube submission checklist

1. Export as an MP4, 16:9, under three minutes.
2. Upload the final live-action cut to YouTube and choose **Public** — not
   Unlisted or Private.
3. Play the published YouTube URL in a private/incognito browser window to
   confirm it opens without sign-in.
4. Paste that exact public `youtube.com/watch?...` URL into the submission
   form, then open the form preview and click the saved link once.

## Honest demo wording

Say **“I built the integration path”** for a guarded external service.

Say **“this live demo shows”** only for an action viewers just watched happen
in the deployed platform.
