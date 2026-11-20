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
    font_delta: int = 0
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
    # Normal and hover fills shared by project and session cards.
    status_backgrounds: dict[str, tuple[str, str]] = dataclass_field(default_factory=dict)


SAGE = Palette()
ORANGE = replace(
    SAGE,
    paper="#feede4", card="#fefbf9", field="#fefafa", ink="#17173b", muted="#60637c",
    line="#ecdacf", hover="#fff0df", accent="#a64a08",
    action="#ff941f", action_hover="#f28917", action_ink="#17173b",
    hero="#ffa12f", hero_border="#e4943c", popup_border="#e3cfc5",
    floating="#ffc48e", scroll="#ddc9bd", scroll_hover="#bd9e8a", tile_radius=12,
    precise_corners=True, font_delta=-1,
    status_colors={
        "running": "#99530b", "stale": "#805422", "completed": "#42634f",
        "interrupted": "#805422", "failed": "#983f48",
    },
    project_colors={
        "unread": ("#e3f8ea", "#d9f3e3", "#b2dbbf", "#35634a"),
        "running": ("#fdf1d7", "#ffebc2", "#edd19c", "#8b4a07"),
        "read": ("#fce3e4", "#f9dce2", "#edc1c8", "#8d424b"),
        "unknown": ("#ebebf6", "#e4e4f2", "#d2d4e8", "#5f576e"),
    },
)

HIGH_CONTRAST_BACKGROUNDS = {
    "running": ("#F7B844", "#F9B22F"),
    "read": ("#ED9EAB", "#EA97A9"),
    "unread": ("#94D9AB", "#8AD4A4"),
    "unknown": ("#BEC8E1", "#B7C1DD"),
}
VIVID_PASTEL_BACKGROUNDS = {
    "running": ("#FFD77D", "#FFD168"),
    "read": ("#F9BCCB", "#F6B5C9"),
    "unread": ("#AEE1BC", "#A4DCB5"),
    "unknown": ("#D5D8EF", "#CED1EB"),
}
ORANGE_MAIN = replace(
    ORANGE,
    status_backgrounds={
        "running": VIVID_PASTEL_BACKGROUNDS["unread"],
        "unread": VIVID_PASTEL_BACKGROUNDS["running"],
        "read": ("#F7EEEA", "#F3E7E2"),
        "unknown": VIVID_PASTEL_BACKGROUNDS["unknown"],
    },
)

# Normal and selected fills for the project tiles only.
PROJECT_COLOR_DEMOS = {
    "vivid-pastels": ("鲜明粉彩", VIVID_PASTEL_BACKGROUNDS),
    "high-contrast": ("最醒目", HIGH_CONTRAST_BACKGROUNDS),
}


def palette_for(widget):
    return getattr(widget.winfo_toplevel(), "notes_palette", SAGE)
