"""Drive a live viser 3D scene from Leika's dock.

The viser server owns the 3D scene; Leika embeds viser's client as a pane
and provides the controls. Each control callback mutates the viser scene
directly, so the Leika dock stands in for viser's own GUI panel.

Requires viser: ``pip install "leika[examples]"``.
"""

from __future__ import annotations

import numpy as np
import viser

import leika


def main() -> None:
    # A concrete port: released viser does not report the bound port for
    # port=0. If 8080 is taken, viser probes upward and get_port() reports
    # the port it actually bound.
    viser_server = viser.ViserServer(port=8080, verbose=False)
    with leika.Server(workspace_id="viser-scene", label="Leika viser") as server:
        server.panes.add_viser(viser_server, pane_id="scene", title="Point cloud")

        count = server.gui.add_slider("Points", min=100, max=20_000, step=100, initial_value=4_000)
        size = server.gui.add_slider(
            "Point size", min=0.005, max=0.1, step=0.005, initial_value=0.02
        )
        color = server.gui.add_rgb("Color", initial_value=(230, 180, 80))

        def rebuild(_: object = None) -> None:
            rng = np.random.default_rng(0)
            points = rng.normal(size=(int(count.value), 3)).astype(np.float32)
            colors = np.tile(np.array(color.value, dtype=np.uint8), (points.shape[0], 1))
            viser_server.scene.add_point_cloud(
                "/cloud",
                points=points,
                colors=colors,
                point_size=float(size.value),
            )

        count.on_update(rebuild)
        size.on_update(rebuild)
        color.on_update(rebuild)
        rebuild()

        print(f"Open {server.url}")
        try:
            server.sleep_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
