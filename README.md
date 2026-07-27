# Leika

Leika is a lightweight canvas for interactive Python visualizations.

## Quickstart

```bash
pip install leika            # Core functionality
pip install "leika[plotly]"  # Plotly panes and GUI figures
```

```python
import time

import numpy as np
import leika

server = leika.Server(workspace_id="quickstart", label="Leika quickstart")
image = server.panes.add_image(
    np.zeros((360, 640, 3), dtype=np.uint8),
    pane_id="camera",
    title="Live image",
    fit="fill",
)
gain = server.gui.add_slider(
    "Gain", min=0.0, max=2.0, step=0.01, initial_value=1.0
)

phase = 0.0
while True:
    x = np.linspace(0.0, 8.0, 640, dtype=np.float32)
    signal = 127.5 + 127.5 * np.sin(x + phase) * gain.value
    frame = np.broadcast_to(signal[None, :, None], (360, 640, 3))
    image.update(np.clip(frame, 0, 255).astype(np.uint8))
    phase += 0.08
    time.sleep(1 / 30)
```

Run the script and open the URL printed in the terminal (by default
`http://localhost:8080`). Use an explicit `workspace_id` and stable `pane_id`s
when you want the browser to restore a layout after a Python restart.

## Learn More

- [Architecture](docs/architecture.md): transport, layout ownership, and
  update flow.
- [Examples](docs/examples.md): runnable demos from the repository.
- [Development](docs/development.md): local checks, browser builds, and
  packaging.

Note that Leika's sole function is relaying formed visualizations and does not
replace software like `matplotlib` or `plotly`.

## Acknowledgments

Leika is inspired by [Viser](https://github.com/nerfstudio-project/viser)
(Apache-2.0) and built on its GUI surface and websocket transport. Thanks to
the Viser authors and contributors.
