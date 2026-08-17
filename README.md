<h1 align="center">
  <img
    src="https://raw.githubusercontent.com/willjhliang/leika/main/docs/_static/leika.svg"
    alt=""
    width="44"
    align="absmiddle"
  />
  leika
</h1>

Leika is a lightweight canvas for interactive Python visualizations.

![A Leika workspace open in the browser](https://github.com/user-attachments/assets/7ca2ffec-db3e-4341-834d-393a1e4572e7)

## Quickstart

```bash
pip install leika              # Core functionality
pip install "leika[examples]"  # Example demo dependencies
```

```python
import time

import numpy as np
import leika

with leika.Server(workspace_id="quickstart", label="Leika quickstart") as server:
    image = server.panes.add_image(
        np.zeros((360, 640, 3), dtype=np.uint8),
        pane_id="camera",
        title="Live image",
        fit="fill",
    )
    gain = server.gui.add_slider("Gain", min=0.0, max=2.0, step=0.01, initial_value=1.0)

    phase = 0.0
    try:
        while True:
            x = np.linspace(0.0, 8.0, 640, dtype=np.float32)
            signal = 127.5 + 127.5 * np.sin(x + phase) * gain.value
            frame = np.broadcast_to(signal[None, :, None], (360, 640, 3))
            image.update(np.clip(frame, 0, 255).astype(np.uint8))
            phase += 0.08
            time.sleep(1 / 30)
    except KeyboardInterrupt:
        pass
```

Run the script and open the URL printed in the terminal (by default
`http://localhost:8080`). `label` names the default page shown in the dock
header. `server.panes` is the same pane API as `server.pages.default.panes`, so
existing one-page applications need no structural changes.

Add named pages when one canvas is not enough:

```python
with leika.Server(workspace_id="experiment", label="Live signals") as server:
    server.panes.add_image(frame, pane_id="camera")

    analysis = server.pages.add("Analysis", page_id="analysis")
    analysis.panes.add_plotly(figure, pane_id="loss")
```

Each viewer's selected page and each page's arrangement are saved locally in
the browser. Use an explicit `workspace_id` and stable `page_id` and `pane_id`
values when those choices and layouts should survive a Python restart.

## Learn More

- [Documentation](https://willjhliang.github.io/leika/): guides and the full
  API reference.
- [Changelog](https://github.com/willjhliang/leika/blob/main/CHANGELOG.md):
  release highlights, compatibility notes, and migration guidance.
- [Panes](https://willjhliang.github.io/leika/panes.html): the image,
  matplotlib, Plotly, and viser surfaces, and how they are laid out.
- [Architecture](https://willjhliang.github.io/leika/architecture.html):
  transport, layout ownership, and update flow.
- [Examples](https://willjhliang.github.io/leika/examples.html): runnable demos
  from the repository.
- [Development](https://willjhliang.github.io/leika/development.html): local
  checks, browser builds, and packaging.

Leika relays visualizations you create; it does not replace libraries such as
`matplotlib` or `plotly`.

## Acknowledgments

Leika is inspired by [Viser](https://github.com/viser-project/viser)
(Apache-2.0) and built on its GUI surface and websocket transport. Thanks to
the Viser authors and contributors.
