import json
import os
import pathlib

from img import Img


class SpriteSequence:
    """Frames and timing for one animation state (e.g. .../BB/states/idle/)."""

    def __init__(self, state_folder: str | pathlib.Path):
        state_folder = pathlib.Path(state_folder)

        with open(state_folder / "config.json", "r") as f:
            config = json.load(f)

        graphics = config["graphics"]
        self.fps: float = graphics["frames_per_sec"]
        self.is_loop: bool = graphics["is_loop"]
        self.next_state_when_finished: str = config["physics"]["next_state_when_finished"]

        sprite_paths = sorted(
            (state_folder / "sprites").glob("*.png"),
            key=lambda p: int(p.stem),
        )
        # cv2.imread cannot open absolute paths containing non-ASCII
        # characters on Windows, so read relative to the working directory.
        self.frames: list[Img] = [
            Img().read(os.path.relpath(p, start=os.getcwd())) for p in sprite_paths
        ]

    def get_frame(self, elapsed_sec: float) -> Img:
        """Return the frame that should be showing after `elapsed_sec` seconds."""
        frame_index = int(elapsed_sec * self.fps)

        if self.is_loop:
            frame_index %= len(self.frames)
        else:
            frame_index = min(frame_index, len(self.frames) - 1)

        return self.frames[frame_index]
