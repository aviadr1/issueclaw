# Terminal demo: mirror fixture issues into local markdown, then search them.
# No Linear API key. docs/demo_mirror.py uses the real renderer.
#
# Regenerate from the repo root. Needs VHS, ttyd, ffmpeg, and rg.
# Create the project env first so the hidden setup can activate it:
#
#   uv sync
#   vhs docs/demo.tape
#
# Output is docs/demo.gif.

Output docs/demo.gif

Require rg

Set Shell "bash"
Set Theme "Catppuccin Mocha"
Set FontSize 18
Set Width 920
Set Height 500
Set Padding 20
Set Framerate 20
Set TypingSpeed 28ms
Set WindowBar Colorful

Env PS1 "$ "

Hide
Type "source .venv/bin/activate"
Enter
Sleep 500ms
Type "export PS1='$ '"
Enter
Sleep 300ms
Type "rm -rf /tmp/issueclaw-demo"
Enter
Sleep 300ms
Show

Type "python docs/demo_mirror.py /tmp/issueclaw-demo"
Enter
Sleep 1.5s

Type "cd /tmp/issueclaw-demo"
Enter
Sleep 400ms

Type "rg -n login linear"
Enter
Sleep 3s
