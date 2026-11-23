# Prompt version

Live notes and live drafts are asked for by the text in `src/prompts.py`. `PROMPT_VERSION` is the label for that text. The current version is `2026.11.1`.

A draft stores the version that produced it. A saved sample stores `saved-demo` instead, because a person wrote that text. The review screen shows the label on the draft. The local log stores it on the send row.

## What this version asks for

Notes have to separate evidence from inferences.

- Evidence is a claim plus a short quote copied from the page.
- An inference is a guess, with a basis, and it is labeled as a guess.
- The prompt tells the model not to invent a number, a customer, or a sender company.

The email has to name the company, use one concrete detail from the notes, stay under 200 words, and end with one question that asks for a short conversation. An inference can be a question. It should not be stated as a fact the page said.

## What the version does not do

`make eval` does not call the model. It scores text that is already in the repo. Bumping `PROMPT_VERSION` does not change those scores. It marks which instructions a later live draft used, so a prompt edit shows up in git and on the draft.

The review screen runs the string checks on the draft you are editing. A failing check does not block Confirm. The checks cannot tell whether a paraphrase is fair.

When the instructions change, change `PROMPT_VERSION` in the same commit. `docs/PRODUCT.md` repeats the version inside the Success metrics section, and a test fails if that section and `make eval` disagree.
