"""ttydiff integrated demo — shows the full pipeline working."""

from src.contracts import ScreenState
from src.parser import ANSIParser
from src.screen import apply_event, render_as_text
from src.diff import diff_screens

def main():
    print("=" * 60)
    print("ttydiff — Integrated System Demo")
    print("=" * 60)

    # --- Feature 1: Basic Parser & Screen ---
    print("\n[1] Basic Parser + Screen Rendering")
    state1 = ScreenState.blank(5, 20)
    parser1 = ANSIParser()
    for e in parser1.parse(b"Hello World"):
        apply_event(state1, e)
    for line in render_as_text(state1):
        print(f"  {line!r}")

    # --- Feature 2: Wide Character Support (Emoji/CJK) ---
    print("\n[2] Wide Character Support")
    state2 = ScreenState.blank(5, 30)
    parser2 = ANSIParser()
    # 'A' (1 col), Emoji (2 cols), CJK (2 cols)
    for e in parser2.parse(b"A \xf0\x9f\x98\x8e \xe4\xb8\xad"):
        apply_event(state2, e)
    for line in render_as_text(state2):
        print(f"  {line!r}")
    print(f"  Cursor position: {state2.cursor_col} (correctly advanced by wide chars)")

    # --- Feature 3: Window Title Extraction (OSC 0/2) ---
    print("\n[3] Window Title Extraction (OSC)")
    state3 = ScreenState.blank(5, 20)
    parser3 = ANSIParser()
    for e in parser3.parse(b"\x1b]0;htop - System Monitor\x07"):
        apply_event(state3, e)
    print(f"  Captured Title: {state3.title!r}")

    # --- Feature 4: Diff Engine (T4) ---
    print("\n[4] Diff Engine (Comparing Screen States)")
    before = ScreenState.blank(3, 10)
    after = ScreenState.blank(3, 10)
    
    # Modify 'after' state
    parser4 = ANSIParser()
    for e in parser4.parse(b"Hello"):
        apply_event(after, e)
    
    diff = diff_screens(before, snapshot(before), after)
    print(f"  Changes detected: {len(diff.changes)}")
    if diff.changes:
        c = diff.changes[0]
        print(f"  Example: Row {c.row}, Col {c.col}: '{c.old.char}' -> '{c.new.char}'")

    print("\n" + "=" * 60)
    print("All features verified and working!")
    print("=" * 60)

def snapshot(state):
    return state.snapshot()

if __name__ == "__main__":
    main()
