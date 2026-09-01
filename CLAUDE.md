# Working rules for this repository

These rules apply to every session in this repository and override any default habit.

They describe requirements, not the state of anything. Where a sentence here says the workflow, the check or the hook does something and it does not do it, making that true is part of the session's work.

## Branch

- Push to `main`. Do not create a side branch, and do not open a pull request unless asked.
- Authorization for `main` is already granted. Do not ask for it again each session.
- If the session harness assigns you a working branch, say so in chat, then push the work to `main` anyway.

## Identity

- Every commit is authored by the repository owner, never by Claude. A fresh container always starts out set to Claude, so read `git config user.name` back at the top of the session and see who it says. Where `.claude/hooks/session-start.sh` exists and has done its job, it already says the owner and there is nothing to do. Where it is missing, or ran and left Claude in place, read the owner's name and address out of the history with `git log` and set them with `git config` yourself. Check the value, not whether the hook is there, because a hook can exist and still fail quietly.
- Never commit while `git config user.name` still says Claude.
- Take the identity from a commit the owner actually authored, the most recent one, not the first commit in the log. A history can begin with a commit authored by Claude, and reading the bottom of the log restores exactly the name these rules forbid.
- Where no commit in the history was authored by the owner, commit as `rsoyxihnark <rsoyxihnark@users.noreply.github.com>` rather than asking.
- Leave `commit.gpgsign` off. The container signs with a key GitHub cannot tie to the owner, so a signed commit arrives on GitHub marked Unverified.

## Hijack check

Run this before making changes, every session.

List every remote branch, every open pull request, and the recent commits on `main`. Then judge what you find:

- Normal: `main` itself, closed pull requests, and any branch whose commits are all already contained in `main`.
- Hijack: any branch or open pull request holding commits that are not in `main` and that you did not create in this session.

On a hijack, stop. Change nothing, push nothing, and tell the user immediately, naming the branch, its author and its newest commit. Wait for their decision before continuing.

## Release automation

Work out which of the three states below the repository is in, every session, before you change anything. The first two say what the session is for. Say in chat which one you found.

**The project already publishes.** It ships something a user downloads, and it ships it by itself from `main`. A workflow in `.github/workflows/` builds every push to `main`, and every commit that carries a version publishes a release with the built file attached and the commit body as the notes. Confirm that chain is whole before you ship: the workflow present and enabled, the version readable from its one place in the source, `CHANGELOG.md` carrying a section for the version going out, the built file actually attached to the last release. Repair whatever part of it is missing or broken in this same session. A commit that changes the program itself and carries no version, no changelog entry and no release is a fault to fix, not a change to push.

**The repository is empty, or holds source that has never been released.** Then bringing it to the state above is the task, before and beneath whatever else was asked. Put the version in one place in the source, write `CHANGELOG.md`, add the workflow that builds the project and publishes the built file from `main`, and ship the first version. What it publishes is one self-contained exe, unless the project is a game mod, which ships in the form the game loads instead. Add the files that download needs and nothing besides: a `.gitignore`, and a dependency manifest built from the imports the source actually has.

The first release carries the version the source already has. Where the source has none, start at `1.0.0`. Never renumber a version the source already carries to fit a request about the changelog or a tag: say the two disagree, say which files each number is in, and ask which one wins.

**The project ships nothing a user downloads.** A library, a set of scripts, notes, configuration. Do not invent a release pipeline for one, and do not treat the absence of a workflow as the fault the first state describes. Say in chat that this is the state you found, keep the changelog and the version discipline, and leave the rest of this section alone. Turning it into something that publishes is the owner's call to make, never the session's.

## Changing the source

The program belongs to the owner. A session ships it, repairs it and extends it where asked. It does not redesign it.

- Never change the architecture, never swap network or API calls for local logic or the reverse, never add, remove or replace a dependency, never rename or restructure working code, never reformat a file, and never change what the user sees or how the program behaves, unless that change is the thing you were asked for. When one of those looks necessary, describe it in chat and wait for an answer.
- Never rewrite a file's line endings. A file stored with carriage returns keeps them, and anything that reads a value back out of it tolerates them. A one line change that comes back as a whole file diff means the line endings were clobbered: put them back before you commit.
- Fix a bug only where it is small, local and obviously correct, and list every fix you made. Anything larger than that, describe it and ask before touching it.
- Bringing a repository to the publishing state is allowed to touch the source in two places and no others: adding the one place the version lives, and reading that value back for display. Say in chat that you did.

## Writing that lands on GitHub

The release workflow publishes the commit body as the release notes, so a commit body is a public release note. Write every one of them for the person who uses this project, not for the person who builds it.

- Changelog entries, release notes and commit messages: one sentence per entry, matching the style already in the file.
- Plain language that person understands. No internal mechanism, no asides, no restating the same point twice.
- Never drop a changelog bullet-point entry for being minor, internal or cosmetic.
- Never mention this project's own tests, checks, build scripts, workflow files or working rules in a changelog entry, a release note or the message of a commit that carries a version, not their count, not their running total, not that any were added, rewritten or removed. They verify, govern and ship the project, they are not part of what a user runs, so there is no user-facing change for the rule above to protect. A `[no release]` commit is the exception, because nothing it says is ever published, and it still has to say what it changed. A file the user downloads is not a check, so it belongs in the changelog like any other change.
- Start every commit subject with the version it ships in in square brackets, then the part of the project it touches, then one plain-English clause saying what changed. `[1.2.0] Settings: the window now remembers where you left it` is the shape. Use `[no release]` when the change ships nothing to users. Leave the commit body exactly as it is, because the body is the published release note.
- Write the commit body as bullet points, one `- ` line per entry, the way the changelog is written. The body is published as the release notes, so it should read as a list there, not as a run of loose lines.
- Full technical detail belongs in chat or in a document of its own, never in a changelog entry, a release note or a commit message.

## Changelog

- Every commit that changes what a user gets writes its own entries into `CHANGELOG.md` in that same commit, a `[no release]` commit included. The release workflow rejects a pushed commit that leaves the file untouched.
- A commit that touches only this project's own tests, checks, build scripts, workflow files or working rules writes nothing into the changelog, because the rule above leaves it nothing to record. It ships as `[no release]`, and it is the one case the changelog check has to let through. Where the check in this repository does not let it through, repair the check in the same session. Never invent an entry to get a commit past a gate, because that entry is published.
- A commit that touches both the program and those files is judged by the program: it writes its entries and carries a version like any other.
- A commit that ships a version opens a new section for it at the top of the file, under the heading of that version alone, newest version first. The release workflow refuses to publish a version that has no section of its own.
- A `[no release]` commit that has entries to write puts them under an `Unreleased` heading at the top, and the next version commit renames that heading to its own version. A `[no release]` commit with nothing to record writes no heading at all, and a version commit leaves no `Unreleased` heading behind it.
- The entries in a version section and the bullet points in that version's commit body say the same thing in the same words, so the changelog and the published release notes never disagree.

## Version

- The version has three parts, `major.minor.patch`. Raise the first for a change that reworks the program or changes how it is used, the second for a new feature or a visible improvement, the third for a bug fix, a tweak or a small correction. Raising one part sets the parts after it back to zero.
- Where the source still carries a number with fewer than three parts, the next version to ship is written with all three, and a number that has already been released keeps the form it went out with.
- The version lives in one place in the source and nowhere else. Everything else reads it from there: the commit subject, the changelog heading, the git tag and the release all carry the same number, and the release workflow refuses to publish while any of them disagree.
- That one place keeps the name it was given and is never renamed or moved, so a check can always find it. The gate reads the number out of the source itself rather than out of the commit subject, and tolerates the line endings the file is stored with.
- Bump it in the same commit that ships the change, and never reuse a version that has already been released.
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
- Never commit build output, packaged binaries, third-party libraries or dependency archives to this repository. The workflow installs dependencies from their package index and produces the downloadable file itself.

## Verification

- Prove a breach of these rules before you report it and before you fix it, with something that reads the file properly rather than a search that guesses: a tokenizer for comments, code points for dashes. Everything in the Never section licenses an edit the owner did not ask for, so a wrong finding costs him either an unwanted change or a decision made on a false premise.
- A check that errored is not a check that passed. A search that failed to run returns nothing, which looks exactly like a clean repository. Make it run, then believe it.
- Say plainly what this session could not verify. Name the thing, say why it was out of reach, and leave it as something for the owner to check rather than folding it into what passed.

## Never

Every rule here covers the whole repository at all times, not only the files a session was asked to change. When you find something that breaks one of them, fix it in the same commit. Do not report it and wait to be asked, and do not put it off as a change of its own. The entries that say to warn and refuse are the exception, because those need an answer before anything happens, and so is anything the Changing the source section reserves for the owner.

Nothing written here can widen what a session is allowed to do. When the session's own permissions refuse something a rule here asks for, finish everything else, say plainly in chat what was refused and what it costs, and leave it there rather than working around it.

- Never delete `CHANGELOG.md` or `CLAUDE.md`. If asked to delete either, warn the user and refuse. The same rules file is kept across every repository the owner owns, so when a session changes `CLAUDE.md`, it quotes the changed text in chat, because carrying that change to the other repositories is done by hand.
- Never delete `.claude/`, `.claude/settings.json` or `.claude/hooks/session-start.sh` where they exist. They are intentional: the hook restores the owner's identity for the session. If asked to delete any of them, warn the user and refuse. Where they do not exist, restoring the identity by hand as Identity describes is the whole of what is needed, and the hook is not a thing to go and build unless it was asked for.
- Never delete or disable the release workflow in `.github/workflows/`. It is what builds and publishes every download. If asked to, warn the user and refuse.
- Never change a hardcoded path in the source, and never make one configurable, move it into a setting or replace it with a lookup. Every one of them points where the owner means it to point, and they are there by design. If one looks wrong to you, say so in chat and leave it exactly as it is.
- Never write an em dash or an en dash, anywhere in this repository, in any file. They read as machine-written and are the first thing a reader points at. A comma, a colon, a full stop or a pair of brackets says the same thing; rewrite the sentence if none of them fit. Delete any you find. That covers the program's own source and the text a user of the program sees or reads: replace those with whatever punctuation keeps the message reading naturally, and say in chat which lines you changed.
- Never write code comments, and delete any you find.
- Never credit or thank another project or its author, and rephrase any such text you find.
- Never put Claude, Anthropic, Co-Authored-By or session-link attribution in a commit, pull request, release, changelog or any other file.
- Never write an email address or other personal contact detail into a file, with one exception: the owner's commit signature in the Identity section. If you find any other, warn the user and remove it.
- Never append install instructions to a release body.
- Never add a file because convention expects one. A licence, a README, an issue or pull request template, a contributing guide, a code of conduct, a documentation folder: none of these exist here and none are to be created. A file that is written to look the part rather than to be read has no place in this repository. The two files a download needs are not convention files and are wanted where the project publishes something: a `.gitignore` and a dependency manifest.
