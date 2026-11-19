# Draft rubric

This is a written check for outreach drafts saved in the repo. `make eval` applies it. The script reads HTML and JSON from disk. It does not call a model, open a socket, or send mail.

A pass means the draft matched these rules. It does not mean the email is fair, welcome, or ready to send. The confirm step is still a person.

## What is scored

Two sets:

- **Saved demo drafts.** Eight drafts: Northwind Analytics and Harbor & Pine Goods, four tones each. These are the drafts `make demo` shows. The page text is the saved HTML under `fixtures/demo`.
- **Fixture drafts.** Twelve fictional company pages under `fixtures/eval`, one hand-written draft each. Some were written to miss a single check, so a perfect column would mean that check never fires. They are not model output.

There is no live Claude score here. A prompt change can still make a live draft worse while this table stays put.

## The six checks

1. **Cites a fact from the page.** The fixture lists phrases that are copied from that company's page. At least one phrase must appear in the subject or body, with the same words, ignoring case. A paraphrase fails, even when it is true. Before scoring, the script checks that every listed phrase is actually on the page. If it is not, the script stops, because the check would be scoring a phrase the fixture invented.

2. **Length within target.** The body is 40 to 200 words. The subject is 1 to 60 characters. Two hundred words is the cap already written into the drafter prompt. Forty words is the floor so a one-line note does not pass.

3. **No banned phrase.** The subject and body must not contain any of these, ignoring case:

   - i hope this email finds you well
   - i hope this finds you well
   - i noticed your company
   - just circling back
   - circle back
   - touch base
   - synergy
   - industry-leading
   - guaranteed results
   - act now
   - limited time
   - dear sir or madam
   - to whom it may concern
   - as per my last email

4. **No invented number.** Every digit string in the subject or body must also appear on the page. "40%" fails when the page never says 40. Numbers written as words ("six weeks") are not checked. That is a hole. The one exception is the ask the drafter prompt already requests: "15-minute" or "15 minutes". Those digits are the meeting length, not a claim about the company.

5. **Names the company.** The draft must contain the company's first word of four or more letters. "Northwind Analytics" passes when the draft says "Northwind". "Harbor & Pine Goods" passes when it says "Harbor". The full legal name is not required. A draft can cite a real page fact and still fail this check.

6. **Clear ask.** Some line of the body has a question mark and, on that same line, one of: chat, call, conversation, minute, meeting, session. Plurals count. "After-hours calls" on one line and "Is Tuesday open?" on another does not count. The question and the ask have to sit together.

## Confirm gate

Separate from draft quality. The question is how often the pipeline stops before send in the situations the test suite covers.

A run counts only when it produced a draft. Stopped means the stage stayed at review and send was not called. A failed scrape, a missing API key, or an unknown demo URL produces no draft, so those runs are listed and left out of the fraction.

`auto_send` plus a recipient is a scripted bypass. The review screen does not mention `auto_send`, so it cannot take that path. Calls that go straight to `send_email` are the confirm step itself. They are not counted as the gate failing open.

## What a pass does not mean

- The draft is true. A phrase can be copied and still be used unfairly. A number on the page can be the wrong number for the sentence.
- The recipient wants the email.
- A live model would score the same way. This table is the saved text only.
- The app will refuse to send. The score is a report. Confirm is still the only stop.

## How to run it

```bash
make eval
```

The same text is the Success metrics section of [PRODUCT.md](PRODUCT.md). A test fails if that section and the script disagree. If you change a saved draft, run `make eval` and update the section with the script's output.
