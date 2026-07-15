import pathlib

from sprite_sequence import SpriteSequence


class AssetLoader:
    """Loads a chess piece's animation states from an assets root folder."""

    def __init__(self, assets_root: str | pathlib.Path):
        self.assets_root = pathlib.Path(assets_root)

    def load(self, piece_code: str) -> dict[str, SpriteSequence]:
        """Return {state_name: SpriteSequence} for every state of `piece_code`."""
        states_folder = self.assets_root / piece_code / "states"

        return {
            state_folder.name: SpriteSequence(state_folder)
            for state_folder in sorted(states_folder.iterdir())
            if state_folder.is_dir()
        }
