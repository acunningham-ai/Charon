"""Charon update mechanism — one command, all sources.

`python -m scripts.update.charon_update` checks every source declared in
`sources.yaml` and offers to apply available updates. The `/charon-update`
slash command + `update-charon` skill provide the interactive UX wrapping
this script.

Source types supported:
  github-self      — checks the harness repo's origin/<branch> for new
                     commits; offers fast-forward pull if working tree clean
  github-vendored  — checks upstream SHA, clones shallow at new SHA, copies
                     files, re-pins SHA, runs post-update smoke test

Add new sources by editing sources.yaml — no code changes needed.
"""
