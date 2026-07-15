import json
import pathlib

from img import Img

DEFAULT_FPS = 10
DEFAULT_IS_LOOP = True
DEFAULT_NEXT_STATE_WHEN_FINISHED = "idle"


class SpriteSequence:
    """Frames and timing for one animation state (e.g. .../BB/states/idle/)."""

    def __init__(self, state_folder: str | pathlib.Path):
        state_folder = pathlib.Path(state_folder)

        config_path = state_folder / "config.json"
        if config_path.exists():
            with open(config_path, "r") as f:
                config = json.load(f)
            self.fps: float = config["graphics"]["frames_per_sec"]
            self.is_loop: bool = config["graphics"]["is_loop"]
            self.next_state_when_finished: str = config["physics"]["next_state_when_finished"]
        else:
            self.fps = DEFAULT_FPS
            self.is_loop = DEFAULT_IS_LOOP
            self.next_state_when_finished = DEFAULT_NEXT_STATE_WHEN_FINISHED

        sprite_paths = sorted(
            (state_folder / "sprites").glob("*.png"),
            key=lambda p: int(p.stem),
        )
        # NOTE: passes the full absolute path directly (per explicit
        # instruction). cv2.imread cannot open absolute paths containing
        # non-ASCII characters on Windows — this will raise
        # FileNotFoundError on any machine where the repo path itself
        # contains such characters (e.g. this one).
        self.frames: list[Img] = [Img().read(p) for p in sprite_paths]

    def get_frame(self, elapsed_sec: float) -> Img:
        """Return the frame that should be showing after `elapsed_sec` seconds."""
        frame_index = int(elapsed_sec * self.fps)

        if self.is_loop:
            frame_index %= len(self.frames)
        else:
            frame_index = min(frame_index, len(self.frames) - 1)

        return self.frames[frame_index]
