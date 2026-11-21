"""Visual palette shared by the main window and its popups."""

from dataclasses import dataclass, field as dataclass_field


@dataclass(frozen=True)
class Palette:
    paper: str = "#feede4"
    card: str = "#fefbf9"
    field: str = "#fefafa"
    ink: str = "#17173b"
    muted: str = "#60637c"
    line: str = "#ecdacf"
    hover: str = "#fff0df"
    accent: str = "#a64a08"
    action: str = "#ff941f"
    action_hover: str = "#f28917"
    hero: str = "#ffa12f"
    hero_border: str = "#e4943c"
    popup_border: str = "#e3cfc5"
    floating: str = "#ffc48e"
    scroll: str = "#ddc9bd"
    scroll_hover: str = "#bd9e8a"
    tile_radius: int = 12
    font_delta: int = -1
    status_colors: dict[str, str] = dataclass_field(default_factory=lambda: {
        "running": "#99530b",
        "stale": "#805422",
        "completed": "#42634f",
        "interrupted": "#805422",
        "failed": "#983f48",
    })
    # Border and status ink.
    project_colors: dict[str, tuple[str, str]] = dataclass_field(default_factory=lambda: {
        "unread": ("#b2dbbf", "#35634a"),
        "running": ("#edd19c", "#8b4a07"),
        "read": ("#edc1c8", "#8d424b"),
        "unknown": ("#d2d4e8", "#5f576e"),
    })
    # Normal and hover fills shared by project and session cards.
    status_backgrounds: dict[str, tuple[str, str]] = dataclass_field(default_factory=lambda: {
        "running": ("#AEE1BC", "#A4DCB5"),
        "unread": ("#FFD77D", "#FFD168"),
        "read": ("#F7EEEA", "#F3E7E2"),
        "unknown": ("#D5D8EF", "#CED1EB"),
    })


ORANGE = Palette()
