---
name: puz-batch
description: Add the next N PUZ-uri of Cluj-Napoca to the clujpug.ro map, one fresh subagent per PUZ running the add-puz skill, one at a time, auditing each commit; in a Claude Code cloud session it also pushes each one to puz-cluj. Use for "/puz-batch 6", "continuă cu următoarele PUZ-uri", or a scheduled batch run, on the laptop or in the cloud.
---

# PUZ batch

Input: how many PUZ-uri (default 6). Optional: `--retry-stopped` to retry recipes
marked `oprit`, and a year or year range such as `2025` or `2022-2023` (default
2020-2026).

Other batch sessions may be running at the same time, each on its own years and
pushing to `puz-cluj`. Never take years you weren't given.

You are the coordinator. You don't process PUZ-uri yourself. Each one is done by a
fresh general-purpose subagent following `.claude/skills/add-puz/SKILL.md`. You
pick the work, run the agents one at a time, check each result, keep `puz-cluj`
clean, and report. No one is watching: decide by these rules and go on.

Run the pipeline as `tools/puz/puz.sh <command>`. It works on the Windows laptop
and on Linux. "Cloud" below means `CLAUDE_CODE_REMOTE` is `true`.

## 1. Start

1. From the repository root, check `git branch --show-current`.
   - In the cloud the clone may start on `master`. Run
     `git fetch origin puz-cluj && git checkout puz-cluj`.
   - On the laptop, if the branch isn't `puz-cluj`, stop and report.
2. `git status --short` must be empty. If it isn't, stop and report.
   - In the cloud, also run `git pull --rebase origin puz-cluj`: a scheduled run
     must start from what earlier runs pushed.
   - In the cloud, set the merge driver that `.gitattributes` names for `puz.json`:
     `git config merge.puzindex.driver "tools/puz/puz.sh merge-index %O %A %B"`.
     Parallel sessions add entries at the same places in `puz.json`; with the
     driver, rebasing onto them merges entry by entry instead of conflicting.
3. Run `tools/puz/puz.sh doctor`.
   - Any `FAIL`: stop and report what is missing.
     - Python packages or poppler missing: the environment's setup script didn't
       run.
     - A domain unreachable: it is missing from the environment's allowed domains.
       Name it.
   - `WARN` for Overpass or Nominatim: go on. OpenStreetMap comes from the extract
     in the repository; those servers are only a fallback.
   - `WARN` for the OSM extract (missing or old): go on, and put it in the report.
4. Run `tools/puz/puz.sh next --count N`. Add `--retry-stopped` if asked, and
   `--from-year A --to-year B` for the years given (`2025` is
   `--from-year 2025 --to-year 2025`). Keep its progress line for the report. If
   the list is empty, report that the range is done.

## 2. One agent per PUZ, one at a time

Never run two agents at once: they share `puz.json` and `SHA256SUMS`. For each
`<an> <nr>` from the list:

1. Note the time and `git rev-parse HEAD` (call it `<start>`).
2. Launch a general-purpose subagent (Agent tool) with the prompt below, filled in.
   Wait for it to finish before doing anything else.

   ```
   You are adding one PUZ (Plan Urbanistic Zonal) of Cluj-Napoca to the clujpug.ro
   map. The repository is the git root of the current working directory, on branch
   puz-cluj.

   Your input is: **<an> <nr>** (council decision HCL <nr>/<an>).

   Follow the project skill `.claude/skills/add-puz/SKILL.md` exactly: read it
   first, then `tools/puz/README.md`, then do every step yourself. You have no one to
   ask: decide, check your own work against the quality gates, and either publish
   and commit, or record a stop and commit that, as the skill describes. Do not
   push: the coordinator does.

   Run the pipeline as `tools/puz/puz.sh <command> ...` with the Bash tool. Look at
   images (renders and crops in puz_cache/) with the Read tool. The OpenStreetMap
   commands read the OSM extract in the repository; `--live` asks the public
   Overpass servers, which are often busy, only for features newer than it.

   End with the report the skill asks for, in Romanian.
   ```

3. When it returns, run `git log --oneline <start>..HEAD` and `git status --short`.
   - **One new commit.** Audit it: `tools/puz/puz.sh audit puzuri/cluj-napoca/<id>.json`.
     If the agent worked on a base PUZ instead (an amendment), audit the recipe
     its commit published.
     - Exit 0, `OK`: keep it.
     - Exit 2, `DE VERIFICAT`: read each `VERIFICĂ` line. The word is fine when it
       sits in a street name, in the project's own name as the decision's title
       gives it, or is an ordinary word. Keep the commit and mention it in the
       report. If a landowner, person or company, is named, treat it as below.
       When the line says the names couldn't be read, read them in the decision's
       text and look for them yourself in the recipe, the `puz.json` entry and the
       commit message; keep the commit if none is there.
     - Exit 1, `PROBLEME`: don't fix it and don't push it to `puz-cluj`. Move it
       aside: `git branch puz-review/<id>`, then `git reset --hard <start>`. In the
       cloud, run `git push origin puz-review/<id>`. Go on with the next PUZ.
   - **No new commit, clean tree.** The agent stopped before writing anything.
     Note why and go on.
   - **No new commit, changes in the tree.** The agent was cut off. Keep what it
     learned:
     1. Drop any half-published files: `git checkout -- ClujPugWeb/wwwroot/puz/puz.json`
        and `rm -rf ClujPugWeb/wwwroot/puz/<id>`.
     2. Commit only `puzuri/cluj-napoca/<id>.json` and
        `puzuri/cluj-napoca/documente/SHA256SUMS`, as
        `PUZ HCL <nr>/<an> – neterminat (rulare întreruptă)`.
     3. `next` lists the PUZ first next time, and its agent resumes it.
     4. Anything else left changed: stop and report.
4. In the cloud, push each kept commit right away: `git push origin puz-cluj`. A
   session can end at any moment, and unpushed work is lost with it.
   - Rejected because someone pushed meanwhile: `git pull --rebase origin puz-cluj`
     and push again.
   - The rebase conflicts: `git rebase --abort`, stop and report. Say which files
     conflicted. In `puz.json`, check `git config merge.puzindex.driver` was set;
     in a recipe, another session is working on the same years.
   - On the laptop, never push. The owner pushes.
5. Note for the report:
   - the outcome: publicat, integrat în `<base>`, oprit (with the reason), pus
     deoparte, or întrerupt;
   - the commit, the minutes taken, the rms;
   - what the agent asked a human to look at.

## 3. Stop early

Stop, and report, when:

- two agents in a row are cut off or end in an error. A usage limit looks like
  this;
- two agents in a row stop for the same reason outside the PUZ: network, a missing
  tool, a tool error;
- a push or rebase fails and the rules above don't resolve it.

## 4. Report, in Romanian

- A table: PUZ, rezultat, commit, rms, durată, observații.
- Commits moved aside (`puz-review/<id>`), each with what the audit found.
- For a human, PUZ by PUZ: the agents' interpretations, notable text-vs-plate
  differences, `VERIFICĂ` lines you judged fine.
- Progress: the line from `tools/puz/puz.sh next --count 0`, for your years and
  for all of 2020-2026.
- In the cloud, a reminder: the PDFs downloaded here are not kept (git ignores
  them). On the laptop, after `git pull`, `tools/puz/puz.sh sync-docs` downloads
  them into the backup and checks them against `SHA256SUMS`.
