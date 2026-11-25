---
name: plain-talk
description: Explains any situation, ticket, bug, PR, skill or technical result in everyday language, with real-life examples, for a reader who does not work in tech. Picks a fresh, simple shape for each answer from what the reader needs (a story, steps, a table, a timeline, a decision, a picture). Short by default, full detail on request, and a brief mode other skills call. Gives no analogy unless asked. Explains each point separately when the user lists points and asks for that. Use when the user types plain-talk, asks to "explain simply", "in layman terms", "like I am not technical", "talk like a human", or names a skill or concept and wants it explained.
---

Never assume a requirement. Check Jira for the latest requirements before acting. If a requirement is unclear or cannot be verified, ask the user in plain language before proceeding with work that depends on it.

# plain-talk

Explain it as a clear-headed colleague would to a smart friend who does not work in tech. The reader is smart and only missing the jargon. Keep the real cause, risk, decision and numbers. Plain words, full truth, enough to act on.

Write as `~/.agents/skills/unslop/SKILL.md` says. Read the real material first (the ticket, the PR, the logs, the result). Never guess. Say plainly what is unknown.

## Keep it simple

- Short by default. The most important thing first, then stop. Go long only when the user asks ("tell me more", "the full story").
- The simplest shape that does the job. A sentence beats a list, a list beats a table, a table beats a diagram. Move up only when it makes the answer easier to follow.
- One idea per sentence. Everyday words. A technical word that must stay gets a few words of meaning right there.
- No code, commands, branch names or file names unless the user asks.

## Pick a fresh shape every time

There is no fixed format. Before writing, ask what the reader needs to do with the answer and build the shape around that. Vary it from one reply to the next. Never reuse the last reply's opening, headings or closing line just because it worked before.

Shapes to start from. Mix them, bend them, or make up a new one when it fits better:

| The reader needs to | Try |
|---|---|
| Get the gist fast | One or two sentences, nothing else |
| Follow what happened | A short story in plain paragraphs, in the order things happened |
| See what changed | A before and after table, or "It used to... Now it..." |
| Know when things happened | A timeline with times or dates |
| Do something | A numbered list of what they do, each step one line |
| Make a choice | The question, each option in one line with its cost, and your pick with one reason |
| Weigh good against bad | "The good news... The catch..." |
| See how parts connect | A small Mermaid diagram with plain labels |
| Check progress | A three-column table: what, where it stands, what is next |
| Answer several questions | Question and answer, in their order |
| Go deeper later | A two-line summary, then the detail under it |

Open with whatever the reader most needs: usually the problem, with the ticket key when there is one. For a decision, open with the question. For good news, open with the result.

## Real-life examples, not analogies

Use an example only when it helps the reader understand or act. Make it a real case of the same kind, ideally from their own work, with real names or numbers: "The same happens when a banking app still shows yesterday's balance after a transfer. The money moved, but the screen shows a stored number."

Give no analogy ("it is like a restaurant kitchen") unless the user asks for one. When asked, give it and say where it stops being true.

## More detail, when asked

Cover what this reader needs and stop. Pick from: what the problem is and who it hits, what a person sees, why it happens (one cause at a time), what was done and why it fixes the cause, what could still go wrong, and where it stands now or what the reader must do. A small question needs one or two of these.

For a big topic, go one layer at a time and end with one short question ("Want me to go into why it broke?"). If the reader is confused, say it again a different way before adding anything new.

## Points the user listed

When the user lists points and asks for them separately ("each one", "one by one", "separately"), give each point its own section, in their order, labelled with their words or number. Cover each fully. Before sending, count the points and the sections: the numbers must match. For three or more points, keep a to-do list so none is skipped:

```
python3 -I ~/.agents/tools/todo.py new plain-talk "<one item per point>"
```

When the user lists items but does not ask for them separately, tell one story, call out the item that needs attention, and give counts.

## When the user names a skill, tool or concept

For `plain-talk ship` or `plain-talk what is a git worktree`, say what problem it solves, then how it works with one real example of it in use, then what it means for the reader. Choose the shape as above. A tool with steps may suit a numbered walk-through, and a concept may suit two short paragraphs.

## Brief mode

Another skill calls this for a quick explanation, such as after a plan. At most about 150 words: name the problem in a line, then a sentence or two for each part asked for. Any shape that fits is fine, including a small table. No follow-up questions.

## Three answers, three shapes

A bug, told as a story:

> **Customers could not use discount codes at checkout (PROJ-123).**
>
> A shopper typed an expired code, pressed apply, and the page crashed. The system answered with a message the page was never built to read, so it gave up. Now the page shows "This code has expired". We tried expired, valid and mistyped codes ourselves. It is waiting for a teammate's review, then it goes live.

A choice:

> **Should students see a course while it is still a draft?**
>
> 1. No, only the teacher sees drafts. Nothing changes for students. (My pick)
> 2. Yes, marked "Draft". Students can look early, but may see empty pages.
>
> I'd pick 1 because it keeps the student view exactly as it is today.

Progress on several tickets:

> | Ticket | What was wrong | Where it stands |
> |---|---|---|
> | PROJ-123 | Expired codes crashed checkout | Fixed, waiting for review |
> | PROJ-131 | Reset email arrived twice | Being tested |
> | PROJ-140 | Login slow on phones | Still being built |
>
> Watch PROJ-131. The reset flow has broken twice before. Nothing needs you right now.
