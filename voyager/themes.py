"""Visual themes: each diary can use any of them, and the home page uses the default."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    background: str  # window background
    surface: str  # inputs and lists
    border: str
    button: str
    button_hover: str
    selected: str  # selected tab and list item
    text: str
    accent: str  # headings and highlights


THEMES: dict[str, Theme] = {
    theme.key: theme
    for theme in (
        Theme("voyager", "Voyager midnight", "#141b29", "#202b3d", "#38475d", "#294763", "#396482", "#36516e", "#e6edf5", "#d4af37"),
        Theme("guitar", "Guitar — warm wood", "#2a1b12", "#3b281b", "#6b4a32", "#7a4a25", "#9a5f33", "#8a5a30", "#f6e7d2", "#f0a94a"),
        Theme("violin", "Violin — cherry varnish", "#25100f", "#381918", "#6e3431", "#7a2528", "#9b3236", "#8c2f33", "#f5e4dc", "#e0b24c"),
        Theme("golden-record", "Golden Record", "#17140b", "#26210f", "#5c5126", "#6b5a1a", "#8a7424", "#7d6a1f", "#f4ecd0", "#ffd75e"),
        Theme("aurora", "Aurora", "#0c1f22", "#143036", "#2c6068", "#1d5f66", "#2a7f88", "#25727a", "#e3f6f4", "#6fe3c8"),
        Theme("nebula", "Nebula", "#1a1230", "#271b47", "#4d3a7d", "#4b3487", "#6046a8", "#5a3f9e", "#ece6fa", "#d79bff"),
        Theme("moonlight", "Moonlight (light)", "#eef1f6", "#ffffff", "#b8c2d3", "#c9d6ea", "#b3c5e2", "#a9bfe3", "#1a2233", "#8a6a12"),
    )
}
DEFAULT_THEME = "voyager"
# Each diary starts in a theme that suits its instrument.
INSTRUMENT_THEMES = {"guitar": "guitar", "violin": "violin"}


def build_stylesheet(theme: Theme) -> str:
    return (
        f"QMainWindow,QWidget{{background:{theme.background};color:{theme.text};font-size:14px}} "
        f"QLineEdit,QPlainTextEdit,QListWidget,QComboBox,QSpinBox{{background:{theme.surface};"
        f"border:1px solid {theme.border};padding:7px}} "
        f"QPushButton{{background:{theme.button};border:1px solid {theme.border};"
        f"padding:9px;border-radius:5px;color:{theme.text}}} "
        f"QPushButton:hover{{background:{theme.button_hover}}} "
        f"QTabBar::tab{{padding:10px;background:{theme.surface}}} "
        f"QTabBar::tab:selected{{background:{theme.selected}}} "
        f"QLabel#heading{{font-size:25px;font-weight:bold;color:{theme.accent}}} "
        f"QLabel#subtle{{color:{theme.border}}} "
        f"QPushButton#tile{{background:{theme.surface};border:2px solid {theme.border};"
        f"border-radius:16px;padding:30px;font-size:22px}} "
        f"QPushButton#tile:hover{{border-color:{theme.accent};background:{theme.selected}}} "
        f"QListWidget::item:selected{{background:{theme.selected}}}"
    )
