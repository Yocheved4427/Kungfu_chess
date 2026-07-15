import pathlib

from sprite_sequence import SpriteSequence


class AssetLoader:
    """Loads and caches a chess piece's animation states from an assets root folder."""

    def __init__(self, assets_root: str | pathlib.Path):
        self.assets_root = pathlib.Path(assets_root)
        self._cache: dict[str, dict[str, SpriteSequence]] = {}

    def load(self, piece_code: str) -> dict[str, SpriteSequence]:
        """Return {state_name: SpriteSequence} for every state of `piece_code`.

        Loaded from disk once per `piece_code`; subsequent calls return the
        cached result.
        """
        if piece_code not in self._cache:
            states_folder = self.assets_root / piece_code / "states"
            self._cache[piece_code] = {
                state_folder.name: SpriteSequence(state_folder)
                for state_folder in sorted(states_folder.iterdir())
                if state_folder.is_dir()
            }
        return self._cache[piece_code]

    def get_asset(self, piece_type: str, state_name: str) -> dict:
        """Return {'frames': [Img, ...], 'fps': int, 'loop': bool} for one state."""
        sequence = self.load(piece_type)[state_name]
        return {
            "frames": sequence.frames,
            "fps": sequence.fps,
            "loop": sequence.is_loop,
        }
