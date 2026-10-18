# Working rules for this repository

These rules apply to every session in this repository and override any default habit.

They describe requirements, not the state of anything. Where a sentence here says the workflow, the check or the hook does something and it does not do it, making that true is part of the session's work.

This file is the same in every repository the owner keeps, whatever the project is: a program, a script, a game mod. A rule that names something a project does not have, such as a settings file, a release workflow, a hook or a base file someone else wrote, applies only where that thing exists. A `## This repository` section at the end, where there is one, holds what is true of this repository alone.

## Branch

- `main` is the only branch this repository keeps. Never start another one, locally or on the remote, and do not open a pull request unless asked.
- Push to `main`, naming it: `git push -u origin HEAD:main`. Authorization for `main` is already granted, so do not ask for it again each session.
- The source to work from is `origin/main` as it stands right now, never whatever the container happens to hold. A container can have been cloned days ago, and the history on the remote can have been rewritten since, so `git fetch origin main` and read `HEAD` against `origin/main` at the top of every session, before reading a line of the source and before changing anything.
- Where the two differ and nothing is uncommitted, put the checkout on `origin/main` and carry on: `git reset --hard origin/main`. That is not a decision to put to the owner and it is never asked about, because the remote is the source of truth and the container's copy is only a cache of it. Say in chat which commit you came from and which you moved to, since the old one stays reachable through `git reflog` if it turns out to have mattered. Where the two histories share no ancestor at all, that is a rewritten remote and not a conflict to resolve: the remote still wins.
- Never read the source, commit, or push on top of a checkout you have not read against `origin/main` in this session. Everything you conclude from stale code is wrong in a way that looks right, and a push from a stale copy is what the fetch exists to prevent.
- A container's clone can be shallow, so the history it holds is not the whole history. Read how deep it goes before you conclude anything from it or copy it anywhere, and fetch the rest first.
- Uncommitted changes are the one case that stops. Leave them where they are, say what they are, and ask before anything discards them.
- Never push a branch other than `main` to the remote, not to record work, not to satisfy a check, and not because a tool asked for it. A push that would put a second branch on the remote is refused by `.claude/hooks/no-new-branch.sh`, and the refusal is the rule working, not an obstacle to route around.
- If the session harness assigns you a working branch, say so in chat, then move the checkout to `main` and commit there. Leave the assigned branch exactly as you found it, and never push it. Committing on the assigned branch instead is what leaves a tool counting unpushed commits against a remote copy of that branch which never moves, so moving first is what stops the warning rather than tolerating it. Where `.claude/hooks/session-start.sh` exists it has already moved the checkout and put it on `origin/main`, and it says in its own words which commit it came from and which it moved to; where it does not, `git fetch origin main`, `git checkout main` and `git reset --hard origin/main` is the whole of it.
- A branch already sitting on the remote that is not `main` is not yours to push to or build on. Say in chat that it is there and leave it alone.
- A tool that still reports unpushed commits is measuring the branch you are on against a remote copy of that same branch, rather than against the upstream that branch is set to follow. Read `HEAD` against the branch's own upstream instead. Where those match, nothing is unpushed: say so once and leave it. Pushing a second branch to quiet the warning breaks the rule above.

## Identity

- Every commit is authored by the repository owner, never by Claude or any other agent. Always commit as `rsoyxihnark <rsoyxihnark@users.noreply.github.com>`. That is the one signature this repository uses, and this line is the one place it is written.
- A fresh container starts out set to the agent rather than the owner, so read `git config user.name` and `git config user.email` back at the top of the session and see what they say. Where `.claude/hooks/session-start.sh` exists and has done its job, they already say the signature above and there is nothing to do. Where it is missing, or ran and left something else in place, set both with `git config` yourself. Check the values, not whether the hook is there, because a hook can exist and still fail quietly.
- Never commit while `git config user.name` still names Claude or another agent, or while `git config user.email` says anything but the address above.
- Older commits in the history carry a private address the owner no longer commits under. Never copy an address out of `git log`: the signature above is the only one to set.
- Leave `commit.gpgsign` off. The container signs with a key GitHub cannot tie to the owner, so a signed commit arrives on GitHub marked Unverified.

## Hijack check

Run this before making changes, every session.

List every remote branch, every open pull request, and the recent commits on `main`. Then judge what you find:

- Normal: `main` itself, closed pull requests, and any branch whose commits are all already contained in `main`.
- Hijack: any branch or open pull request holding commits that are not in `main` and that you did not create in this session.

On a hijack, stop. Change nothing, push nothing, and tell the user immediately, naming the branch, its author and its newest commit. Wait for their decision before continuing.

## Release automation

Work out which of the three states below the repository is in, every session, before you change anything. The first two say what the session is for. Say in chat which one you found.

**The project already publishes.** It ships something a user downloads, and it ships it by itself from `main`. A workflow in `.github/workflows/` builds every push to `main`, and every commit that carries a version publishes a release with the built file attached and the commit body as the notes. Confirm that chain is whole before you ship: the workflow present and enabled, the version readable from its one place in the source, `CHANGELOG.md` carrying a section for the version going out, the built file actually attached to the last release, and that file carrying the version stamp the Version section asks for. Repair whatever part of it is missing or broken in this same session. A commit that changes the program itself and carries no version, no changelog entry and no release is a fault to fix, not a change to push.

**The repository is empty, or holds source that has never been released.** Then bringing it to the state above is the task, before and beneath whatever else was asked. Put the version in one place in the source, write `CHANGELOG.md`, add the workflow that builds the project and publishes the built file from `main`, and ship the first version. What it publishes is one self-contained executable for the platform the project targets, an exe on Windows, unless the project is a game mod, which ships in the form the game loads instead. Add the files that download needs and nothing besides: a `.gitignore`, and a dependency manifest built from the imports the source actually has.

The first release carries the version the source already has. Where the source has none, start at `1.0.0`. Never renumber a version the source already carries to fit a request about the changelog or a tag: say the two disagree, say which files each number is in, and ask which one wins.

**The project ships nothing a user downloads.** A library, a set of scripts, notes, configuration. Do not invent a release pipeline for one, and do not treat the absence of a workflow as the fault the first state describes. Say in chat that this is the state you found, keep the changelog and the version discipline, and leave the rest of this section alone. Turning it into something that publishes is the owner's call to make, never the session's.

## Changing the source

The program belongs to the owner. A session ships it, repairs it and extends it where asked. It does not redesign it.

- Never change the architecture, never swap network or API calls for local logic or the reverse, never add, remove or replace a dependency, never rename or restructure working code, never reformat a file, and never change what the user sees or how the program behaves, unless that change is the thing you were asked for. When one of those looks necessary, describe it in chat and wait for an answer.
- Never rewrite a file's line endings. A file stored with carriage returns keeps them, and anything that reads a value back out of it tolerates them. A one line change that comes back as a whole file diff means the line endings were clobbered: put them back before you commit.
- Fix a bug only where it is small, local and obviously correct, and list every fix you made. Anything larger than that, describe it and ask before touching it.
- Where the program keeps its settings in a file beside itself, changing what a setting is called or what kind of value it takes orphans the copy every user already has. Keep the name, and leave the program either reading the old value or saying in its log that it could not and what it used instead.
- Where that file carries its own shape number and the program lifts an older file forward, a setting may be renamed, retyped or split, but only with its step written into the lift in the same commit, and only with the shape number raised. The list of every setting that has ever shipped is kept by a check, so the build refuses a rename or a retype that leaves a saved value stranded. Never edit that list to make the build pass: add the step.
- A setting shown as a list of choices is stored as the position of the choice, so the order the choices ship in is the stored value. Choices are only ever added to the end. Never reorder them, never remove one, and never insert one in the middle, because every user's setting would come back meaning something else.
- Where the owner is the program's only user, what the program has learned as it ran (a record, a score, a trust it built up from what it saw) may be thrown away and learned afresh when a change makes the old record mean something else. Never hold a better formula back to protect such a record, and never write code to carry it forward. The old record is set aside as it loads, and the log says so. This never covers what a user set, which keeps the rules above, and never leaves a save that will not load. Where the program has users other than the owner, a change carries such a record forward instead.
- Bringing a repository to the publishing state is allowed to touch the source in two places and no others: adding the one place the version lives, and reading that value back for display. Say in chat that you did.

## Writing that lands on GitHub

The release workflow publishes the commit body as the release notes, so a commit body is a public release note. Write every one of them for the person who uses this project, not for the person who builds it.

- Changelog entries, release notes and commit messages: one sentence per entry, matching the style already in the file.
- Every entry stands on its own. It is read alone, out of order, months later, with nothing above it, so it never points at a neighbouring entry: no `that deal`, no `that reset`, no `It keeps a record`, no `It now does the same`. Name the thing the entry is about, every time.
- Keep an entry under 140 characters wherever the sense survives it, and never write one longer than 248. A line the reader has to go back over is a line that was too long.
- Plain language that person understands. No internal mechanism, no asides, no restating the same point twice.
- Use the words the program itself uses. Where it names a thing on screen, a setting, a panel, a button, write that name rather than a paraphrase of it, and write the entry the way one user would tell another what changed. A reader should never have to translate it back into the program's own terms. Where the program is a mod, the words belong to the thing it is a mod for, so use those.
- Never drop a changelog bullet-point entry for being minor, internal or cosmetic.
- A change to the README or to `COMPARISON.md` is never written into the changelog, a release note or a commit message. No entry like `The feature list now says ...` is ever written, and none is left in the changelog, the published release notes or the commit history.
- A commit that changes nothing but those pages ships as `[no release]` under a subject that says the page was touched and no more. Where taking such entries out leaves a version with no entries at all, its section goes, and its release and its tag are thrown away with it.
- Something tried and then taken back out leaves the user nothing, so every line written about it goes: the entry that announced it, the entries that changed it while it was there, and the entry that took it away. Out of the changelog, out of the release notes, out of the commit subjects and bodies that carry them. Nothing about it happened in the end, so nothing about it is left to read. Say in chat which entries you took out.
- That covers the whole run of it, however many versions it lasted, and it holds for a setting, a switch, a panel, a diagnostic or anything else one version shipped and a later one withdrew. Where the same version shipped something that survived, that keeps its entry and only the withdrawn part goes.
- An entry recording that something was looked into and left as it was is the same case: nothing reached the user, so nothing is written down.
- Where taking one of these out leaves a version with no entries at all, that version has nothing left to tell anyone: take its section out too, and throw its release and its tag away with it.
- Start every commit subject with the version it ships in in square brackets, then the part of the project it touches, then one plain-English clause saying what changed. `[1.2.0] Settings: the window now remembers where you left it` is the shape. Use `[no release]` when the change ships nothing to users. Leave the commit body exactly as it is, because the body is the published release note.
- Write the commit body as bullet points, one `- ` line per entry, the way the changelog is written. The body is published as the release notes, so it should read as a list there, not as a run of loose lines.
- Full technical detail belongs in chat or in a document of its own, never in a changelog entry, a release note or a commit message.
- Write a fix the way one user would tell another about it: start with `Fixed`, name the thing that was going wrong, and stop. No clause explaining the mechanism behind it, no second sentence saying it again, nothing written to sound clever. These are the owner's own words, written for a game mod of his, and they are the shape to copy in any project:
  - `Fixed TradeLord buying other goods just because they had a higher margin percentage when the ledger had suggested a much better trade`
  - `Fixed rare high value goods (e.g. jewelry) not being offered in the ledger, because they are almost never stocked 10 or more in early game`
  - `Fixed TradeLord valuing a purchase against a buyer days away instead of a nearby one paying almost the same`
  - `Fixed the map marker pointing at the town paying the most in total instead of the one paying the most per day`
  - `Food is now restocked after trading, so your gold and cargo space go to trade goods first`

## Text length

- No text in the program or about it is longer than 248 characters, counted as it is written, spaces and markup included.
- That covers every name, string and comment in the code, and every setting name, hint, tooltip and panel line the program shows, in every language.
- It covers every line and paragraph of the README, the changelog and any other page written for the people who use the project.
- Lines the program writes to its own log are exempt, and so are `CLAUDE.md` and what the `.claude/` hooks print.
- A text over the limit is rephrased until it fits, or split into entries of its own where it is a list, and every fact it carried stays said somewhere.
- Where the project keeps a source check, it refuses the build while any text runs past 248, so a text is measured before it is pushed, not after.

## Changelog

- Every commit that changes what a user gets writes its own entries into `CHANGELOG.md` in that same commit, a `[no release]` commit included. The release workflow rejects a pushed commit that leaves the file untouched.
- A commit that touches only this project's own tests, checks, build scripts, workflow files, working rules, README or `COMPARISON.md` need not write anything into the changelog. It ships as `[no release]`, and it is the one case the changelog check has to let through. Where the check in this repository does not let it through, repair the check in the same session. Never invent an entry to get a commit past a gate, because that entry is published.
- A commit that touches both the program and those files is judged by the program: it writes its entries and carries a version like any other. The one exception is a change that moves working code without altering a single thing the user sees or gets, made so a check can reach it. That has nothing to record, so it writes no entry, ships as `[no release]`, and leaves the version alone. Say plainly in chat that this is what it is, because the marking is the only thing the release gate has to go on.
- A commit that ships a version opens a new section for it at the top of the file, under the heading of that version alone, newest version first. The release workflow refuses to publish a version that has no section of its own.
- A `[no release]` commit that has entries to write puts them under an `Unreleased` heading at the top, and the next version commit renames that heading to its own version, so an improvement or a fix made under `[no release]` always reaches users in the next version that ships rather than being lost between releases. A `[no release]` commit with nothing to record writes no heading at all, and a version commit leaves no `Unreleased` heading behind it.
- The entries in a version section and the bullet points in that version's commit body say the same thing in the same words, so the changelog and the published release notes never disagree.
- A release note that has already gone out carries its own copy of the entry it was made from, so rewording an entry in the changelog leaves the two disagreeing. Bring the published note back in line in the same session, because the published one is what a reader actually sees.

## Version

- The version has three parts, `major.minor.patch`. Raise the first for a change that reworks the program or changes how it is used, the second for a new feature or a visible improvement, the third for a bug fix, a tweak or a small correction. Raising one part sets the parts after it back to zero.
- Which part to raise is decided by what the change does for the person using the program, never by how much of the source it touched or how much new machinery it carried in. A setting added so that something already shipped can be held back, gated or switched off is a correction and raises the third part, however much wiring it needed, because nothing new reaches that person: they get back what they had. A setting raises the second part only where it hands them something they could not do before.
- Where the source still carries a number with fewer than three parts, the next version to ship is written with all three, and a number that has already been released keeps the form it went out with.
- The version lives in one place in the source and nowhere else. Everything else reads it from there: the commit subject, the changelog heading, the git tag and the release all carry the same number, and the release workflow refuses to publish while any of them disagree.
- That one place keeps the name it was given and is never renamed or moved, so a check can always find it. The gate reads the number out of the source itself rather than out of the commit subject, and tolerates the line endings the file is stored with.
- Bump it in the same commit that ships the change, and never reuse a version that has already been released.
- What the project publishes carries the version where the system shows it, so a user reads it off the file itself without starting the program. On Windows that is the exe's own version stamp, the one Explorer lists under File version. A mod carries it wherever the game or its launcher lists the mods it loads. Where the shipped form has no such place at all, the release and the changelog carry the version alone.
- The build writes that stamp from the one place the version lives in the source, never from a number typed a second time, and the workflow refuses to publish a build whose stamp and source disagree.
- A version is published once. To correct a release that has already gone out, ship the fix under the next version rather than reusing the old one.

## Upgrades

- When a compiler, a package manager, a linter, a workflow run or GitHub itself warns that something this project pins is out of date, deprecated or has been moved onto a newer runtime, raise the version in the same session. Do not ask first. The answer is always yes.
- Raising it is not the end of it. Read the next run's log and confirm the warning is gone, because a newer version can sit on the same deprecated runtime and carry the same warning. Where it survives the bump, check what the newest version actually is and keep going until the log comes back clean.
- Say in chat what the warning was and what you raised, so the change is visible even though it was never put to the owner.
- This covers the versions the project depends on: workflow action versions, the runtime a workflow runs on, package dependencies and the toolchain. It does not cover the project's own release version, which the Version section governs.
- Take the upgrade, not the rewrite. When a version cannot be raised without changing what the project does, leave it, say so in chat, and let the owner decide.

## Build

- Never push unless the project builds clean, starts, and its tests pass locally, because every commit that carries a version publishes a release straight from `main`.
- When the project targets a platform this session is not running on, say so in chat, verify everything the session can verify, and treat the release workflow as the gate that has to come back green.

## Working from a base the project did not write

Where the project ships a modified copy of a file someone else wrote, a game script, a vendored source, the edits are the project and the copy around them is not.

- Derive the edit set by comparing the shipped copy against the untouched original, never by reading markers or comments inside the shipped copy. A marker says where someone once edited. It does not say what the edit was, and it cannot tell a line that was inserted from a line that replaced another. Getting that wrong produces a description that rebuilds fine and ships a duplicated call.
- A round trip that starts and ends at the shipped copy proves the description is self consistent, not that it is correct. Correctness needs the untouched original on one side of the comparison, so get the original before shipping rather than after.
- Before shipping a modified copy of someone else's file, prove it is the owner's own file plus the intended difference and nothing else. Ask him for the file if that is the only way to get it. A copy pulled from a mirror can be a different patch of the same thing, and the reverted fixes are invisible until a user reports something unrelated breaking.
- Anchor an edit on its enclosing function as well as on its line. Near identical sibling functions are common in a large file, and a line that looks unique is often the third copy of itself.
- Where a change makes a condition true far more often than the original ever expected, search every place that condition is read for `else if` chains and early returns written while it was rare. Nothing will flag them, they still compile, and the behaviour goes quietly missing.
- Where the base files are stored as UTF-16, `grep` and every other byte oriented search reads them as nothing and reports no matches at all. Nothing warns you, because the search did not fail: it ran, found nothing, and exited quietly, and an empty result looks exactly like a clean answer. A question as ordinary as which files call this function comes back wrong. Decode the file before searching it, and treat any search over the base tree that found nothing as unproven until it has found something you already know is there.

## Verification

- Prove a breach of these rules before you report it and before you fix it, with something that reads the file properly rather than a search that guesses: a tokenizer for comments, code points for dashes. Everything in the Never section licenses an edit the owner did not ask for, so a wrong finding costs him either an unwanted change or a decision made on a false premise.
- A check that errored is not a check that passed. A search that failed to run returns nothing, which looks exactly like a clean repository. Make it run, then believe it.
- A scan that reports nothing has to be pointed at something it must find before its silence means anything. Put the case you already know into a file of its own, run the scan over that, and believe the empty result only once the known case comes back. A scan can run cleanly over a thousand files and be matching nothing at all, and running without error is not the same as working.
- A check that fails because the source moved is rewritten to describe where the source moved to, never loosened until it passes. Where a rule counts something and the count changed for a good reason, change the count and leave the rule saying what it said. Cutting out the part that failed is how a repository ends up with checks that prove nothing.
- A run that looks stuck is usually a clock you misread. Before you call one hung, or cancel it and start it again, read the time off the machine you are on and work out how long it has really been. Wait for the thing that says the work is finished, the published release or the job's own conclusion, rather than a status view that lags behind it.
- Read what is staged before committing, not only what was edited. A tool's own by-products, an interpreter cache, a build directory, get swept in by a broad add, and one staged once stays in the history.
- Taking something out of the working tree does not take it out of the history. Where the point of a change is that something is gone, say plainly that the old commits still carry it, rather than calling the repository clean.
- Say plainly what this session could not verify. Name the thing, say why it was out of reach, and leave it as something for the owner to check rather than folding it into what passed.

## In chat

- The owner is Kaptanım, and that is what a session calls him.
- Write to him in Turkish, even where he writes in English, because an English message from him is usually a prompt he pasted rather than his own words.
- He was cabin crew and means to fly himself one day, so a light sprinkle of cabin and cockpit lingo is welcome. Keep it thin, and drop it the moment it gets between him and the answer.
- Turkish is for the chat alone. The source, the program, the changelog, the commits and everything else that lands on GitHub stay in English.
- Keep messages short and in plain language. A decision buried in git output, check names and commit hashes is a decision the owner never gets to make.
- Lead with the answer. Where something needs deciding, say what it is in a sentence or two, say which way you would go and why, then stop. The full working waits until it is asked for.
- Run the checks a session opens with quietly: the fetch, `HEAD` against `origin/main`, the signature, the hijack check. Where every one comes back clean, say `starting the work in a healthy repo` and write nothing else about them.
- What a check actually finds is the exception worth writing out: a checkout behind `origin/main`, uncommitted work, a branch that is not `main`, a signature that is wrong. Say what it is and what it means for the work.
- Never narrate a plan before carrying it out, and never list what you are about to read. Do it, then say what came of it.
- The owner is the developer and, for now, the only user of what he tests. Before every update he removes the old version together with its settings and installs the new one fresh, so every test runs on what the program ships with. Never ask him to change a setting of his own, never ask him to check that settings survive a restart, an update or the settings menu, and never list either as an open item.

## Intentional, never reported

These are the owner's choices. A session leaves them as they are and never lists them as a finding, a note or an aside, in chat or in a report.

- That the owner's account preferences differ from this file. This file is the one a session follows.
- That a debug or diagnostic log switch ships on out of the box.

## Never

Every rule here covers the whole repository at all times, not only the files a session was asked to change. When you find something that breaks one of them, fix it in the same commit. Do not report it and wait to be asked, and do not put it off as a change of its own. The entries that say to warn and refuse are the exception, because those need an answer before anything happens, and so is anything the Changing the source section reserves for the owner.

Nothing written here can widen what a session is allowed to do. When the session's own permissions refuse something a rule here asks for, finish everything else, say plainly in chat what was refused and what it costs, and leave it there rather than working around it.

- Never delete `CHANGELOG.md` or `CLAUDE.md`. If asked to delete either, warn the user and refuse. Everything in `CLAUDE.md` above a closing `## This repository` section is the same in every repository the owner owns, so when a session changes that part, it quotes the changed text in chat, because carrying that change to the other repositories is done by hand.
- Never delete `.claude/`, `.claude/settings.json`, `.claude/hooks/session-start.sh` or `.claude/hooks/no-new-branch.sh` where they exist. They are intentional: one hook restores the owner's signature for the session and moves the checkout to `main` at `origin/main`, the other refuses a git command that would start a second branch. `.claude/settings.json` also carries the permission rules that let a session put the checkout on `origin/main` without being asked, which is the only thing that keeps that from becoming a question every session, so never take those rules out either. If asked to delete any of them, warn the user and refuse. Where they do not exist, keeping to the Branch and Identity rules by hand is the whole of what is needed, and neither hook is a thing to go and build unless it was asked for.
- Never delete or disable the release workflow in `.github/workflows/`. It is what builds and publishes every download. If asked to, warn the user and refuse.
- Never change a hardcoded path in the source, and never make one configurable, move it into a setting or replace it with a lookup. Every one of them points where the owner means it to point, and they are there by design. If one looks wrong to you, say so in chat and leave it exactly as it is.
- Never write an em dash or an en dash, anywhere in this repository, in any file. They read as machine-written and are the first thing a reader points at. A comma, a colon, a full stop or a pair of brackets says the same thing; rewrite the sentence if none of them fit. Delete any you find. That covers the program's own source and the text a user of the program sees or reads: replace those with whatever punctuation keeps the message reading naturally, and say in chat which lines you changed.
- Never write code comments, and delete any you find. The one exception is a short note recording something that only running the program, or playing the game it modifies, has shown and the code alone does not: write one wherever a session learns such a thing from the owner's test, and never for something reading the code would tell. Start every such note with `Valuable-Run-Lesson:` so it is never mistaken for a comment that has to go, and give that start to any such note already in the code rather than deleting it. A copyright or licence notice in a file someone else wrote is not one of the project's comments: leave it exactly where it is, because the file is only shipped under it.
- Never credit or thank another project or its author, and rephrase any such text you find.
- Never put Claude, Anthropic, another agent, Co-Authored-By or session-link attribution in a commit, pull request, release, changelog or any other file.
- Never write an email address or other personal contact detail into a file, with one exception: the owner's commit signature in the Identity section. If you find any other, warn the user and remove it.
- Never append install instructions to a release body.
- Never add a file because convention expects one. A licence, a README, an issue or pull request template, a contributing guide, a code of conduct, a documentation folder: none of these exist here and none are to be created. A file that is written to look the part rather than to be read has no place in this repository. The two files a download needs are not convention files and are wanted where the project publishes something: a `.gitignore` and a dependency manifest.
