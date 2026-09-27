# Terminal demo: a Linear mirror as plain markdown in git.
#
# No Linear account or API key. The hidden setup seeds a mirror of three
# fixture issues with docs/demo_mirror.py, which writes files with issueclaw's
# own renderer (the same code `issueclaw pull` uses) and commits them.
# Everything on screen after that is real output: `issueclaw status`, `rg`,
# a markdown edit, and `issueclaw diff` previewing what `issueclaw push`
# would send to Linear.
#
# Regenerate from the repo root. Needs VHS, ttyd, ffmpeg, git, and rg:
#
#   uv sync
#   vhs docs/demo.tape
#
# Output is docs/demo.gif.

Output docs/demo.gif

Require rg
Require git

Set Shell "bash"
Set Theme "Catppuccin Mocha"
Set FontSize 16
Set Width 1000
Set Height 640
Set Padding 20
Set Framerate 20
Set TypingSpeed 30ms
Set WindowBar Colorful

Hide
Type "source .venv/bin/activate && export PS1='$ '"
Enter
Type "export GIT_AUTHOR_NAME=dev GIT_AUTHOR_EMAIL=dev@example.com GIT_COMMITTER_NAME=dev GIT_COMMITTER_EMAIL=dev@example.com"
Enter
Type "rm -rf /tmp/issueclaw-demo && python docs/demo_mirror.py /tmp/issueclaw-demo > /dev/null && cd /tmp/issueclaw-demo"
Enter
Type "git -c init.defaultBranch=main init -q && git add -A && git commit -qm 'issueclaw pull'"
Enter
Sleep 1s
Type "clear"
Enter
Sleep 300ms
Show

Type "# Linear, mirrored into git as markdown"
Enter
Type "issueclaw status"
Enter
Sleep 2s

Type "rg -n login linear"
Enter
Sleep 2.5s

Type "head -6 linear/teams/ENG/issues/ENG-31-*.md"
Enter
Sleep 2s

Type "# edit the file, commit, and preview the push to Linear"
Enter
Type "sed -i 's/^status: Todo/status: In Progress/' linear/teams/ENG/issues/ENG-31-*.md"
Enter
Type "git commit -qam 'Start ENG-31'"
Enter
Type "issueclaw diff"
Enter
Sleep 4s
