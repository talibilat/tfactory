# Spec template

`spec.md` follows this layout. Keep the headings: `spec-check.py` reads them. Write the first two sections for someone who does not read code. Put the detail after.

```
# <KEY> spec: <ticket summary>

Status: draft | approved (A<id>) | posted (<date>)
Investigated: <date>. Code read at: <repo>@<commit>, one per repo.
Requirements used: <document, version and date, one line each>

## In plain words
<4 to 6 sentences. What the ticket is really for, who it helps, what changes for them, and what stays the same.>

## What changed from the ticket text
| # | The ticket said | What we found | Evidence |
|---|---|---|---|
<One row for every claim in claims.md marked wrong or unclear.>

## Sub-tasks
| Sub-task | Its real intent, in two lines | Source | Keep, change or drop |
|---|---|---|---|

## What exists today
<Short list. What is already built, where (file:line), and what is in flight (PR, state, owner).>

## Owned elsewhere
| Part | Owned by | Status and owner | What this spec does about it |
|---|---|---|---|
<Every part an open ticket or PR covers. Write "None" when there is none.>

## Design
<How the new behavior plugs in. The switch: its name, where it lives (file:line), its default, and what happens when it is on and when it is off. With the switch off, the old path behaves exactly as today.>

## Decisions
| # | Decision | Options considered | Chosen | Approval | Proof |
|---|---|---|---|---|---|
| D1 | <what had to be decided> | <each option, one line> | <the option the user picked> | A4 | <file:line, Jira quote or research file behind the chosen option> |
<Every hard decision from step 8 and later, each with its approval id. Write "None" when there is none.>

## Requirements
| # | Requirement | Kind | Source | Quote or evidence |
|---|---|---|---|---|
| R1 | <what must be true> | jira | <KEY>, <author>, <date> | "<exact words, 10 characters or more>" |
| R2 | <what must be true> | user | A3 | <what the user approved> |
| R3 | <how it is built> | code | <file:line> | <what the code shows> |

## Acceptance criteria
1. <Each one checkable by a test or a command. End with the requirement ids it proves, such as (R1, R3).>

## Security
| # | Risk | Where (file:line) | What the spec requires |
|---|---|---|---|

## Known bugs and risks
| # | Bug or risk | Where (file:line) | Ticket | Handled by |
|---|---|---|---|---|
<Ticket is the open ticket that covers it, or "draft" when step 9 will propose one.>

## Test plan
<What must be tested and how: unit, API and live run, with the switch on and off.>

## Open questions
| # | Question | Waits on | Asked where |
|---|---|---|---|
<Write "None" when there is none.>
```

## The Jira version

The ticket description is a shorter copy of `spec.md`: In plain words, Sub-tasks, Owned elsewhere, Design, Acceptance criteria, Security, Open questions. Leave out the `file:line` detail unless a developer needs it. Keep the old description at the bottom under "Original description (kept for history)". Save it as `drafts/description-<KEY>.md`.
