"""Drive custom content from Leika's playback bar; no media or simulator required."""

import time

import leika

server = leika.Server()
playback = server.gui.add_playback(duration=10, fps=30, loop=True)
position = server.gui.add_text("Position", "0.00 s", editable=False)

# Replace this assignment with a plot update or Viser pose update. The app owns
# the clock, so expensive rendering can publish actual progress instead.
previous = time.monotonic()
try:
    while True:
        now = time.monotonic()
        state = playback.advance(now - previous)
        previous = now
        position.value = f"{state.time:.2f} s"
        time.sleep(1 / 30)
except KeyboardInterrupt:
    server.stop()
