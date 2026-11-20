"""Visual palettes shared by the main window and its popups."""

from dataclasses import dataclass, field as dataclass_field, replace


@dataclass(frozen=True)
class Palette:
    paper: str = "#f5f0e6"
    card: str = "#fffdf6"
    field: str = "#fffcf4"
    ink: str = "#493b30"
    muted: str = "#706252"
    line: str = "#e3d8c4"
    hover: str = "#edf1e6"
    accent: str = "#3e6653"
    action: str = "#3e6653"
    action_hover: str = "#305441"
    action_ink: str = "#fffdf4"
    hero: str = "#e5eddd"
    hero_border: str = "#cfdac6"
    popup_border: str = "#c5c9b5"
    floating: str = "#668571"
    scroll: str = "#c8c8ae"
    scroll_hover: str = "#899b82"
    tile_radius: int = 17
    precise_corners: bool = False
    status_colors: dict[str, str] = dataclass_field(default_factory=lambda: {
        "running": "#805921", "stale": "#855b37", "completed": "#425f47",
        "interrupted": "#855b37", "failed": "#92555a",
    })
    # Surface, hover, border, and status ink.
    project_colors: dict[str, tuple[str, str, str, str]] = dataclass_field(default_factory=lambda: {
        "unread": ("#e6eee0", "#dce9d5", "#c1d1b9", "#3f6246"),
        "running": ("#f7ebcf", "#f3e1ba", "#deca9e", "#755320"),
        "read": ("#f3e2df", "#efd8d4", "#dfc3be", "#814c4e"),
        "unknown": ("#eeeae1", "#e9e3d9", "#d9d0c1", "#655d51"),
    })


SAGE = Palette()
ORANGE = replace(
    SAGE,
    paper="#ffe8d8", card="#ffffff", field="#fff9f3", ink="#1c1b42", muted="#625c71",
    line="#efddcf", hover="#fff0df", accent="#a64a08",
    action="#ffa82a", action_hover="#f69618", action_ink="#1c1b42",
    hero="#ffa82a", hero_border="#f6a12a", popup_border="#eac9b2",
    floating="#ffb348", scroll="#e9b791", scroll_hover="#cd8753", tile_radius=22,
    precise_corners=True,
    status_colors={
        "running": "#99530b", "stale": "#805422", "completed": "#42634f",
        "interrupted": "#805422", "failed": "#983f48",
    },
    project_colors={
        "unread": ("#edf7ed", "#e2f2e4", "#c9e0cf", "#35634a"),
        "running": ("#fff1d6", "#ffe8bc", "#edd19c", "#8b4a07"),
        "read": ("#fff1ef", "#ffe6e0", "#efd1cb", "#8d424b"),
        "unknown": ("#f7f5fb", "#f0ecf7", "#e1dbeb", "#5f576e"),
    },
)


def palette_for(widget):
    return getattr(widget.winfo_toplevel(), "notes_palette", SAGE)
