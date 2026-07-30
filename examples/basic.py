"""Stream a NumPy image and control it from Leika's hover GUI."""

from __future__ import annotations

import time

import numpy as np

import leika

HEIGHT = 360
WIDTH = 640
X = np.linspace(0.0, 2.0 * np.pi, WIDTH, dtype=np.float32)
Y = np.linspace(0.0, 2.0 * np.pi, HEIGHT, dtype=np.float32)[:, None]


def render(phase: float, gain: float) -> np.ndarray:
    wave = 0.5 + 0.5 * np.sin(X[None, :] * 2.0 + np.cos(Y * 1.5) + phase)
    red = 255.0 * wave
    green = 255.0 * np.clip(gain * (1.0 - wave), 0.0, 1.0)
    blue = 160.0 + 95.0 * np.sin(Y + phase)
    blue = np.broadcast_to(blue, wave.shape)
    return np.clip(np.stack((red, green, blue), axis=-1), 0, 255).astype(np.uint8)


def main() -> None:
    with leika.Server(workspace_id="basic", label="Leika basic") as server:
        gain = server.gui.add_slider("Gain", min=0.0, max=2.0, step=0.01, initial_value=1.0)
        animate = server.gui.add_checkbox("Animate", initial_value=True)
        pane = server.panes.add_image(
            render(0.0, gain.value),
            pane_id="live-image",
            title="Live NumPy image",
            fit="fill",
            format="jpeg",
            jpeg_quality=85,
        )

        print(f"Open {server.url}")
        phase = 0.0
        try:
            while True:
                if animate.value:
                    phase += 0.08
                    pane.update(render(phase, gain.value))
                time.sleep(1.0 / 30.0)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
