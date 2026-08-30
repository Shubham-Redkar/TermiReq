"""Full pipeline integration demo: Parser -> Screen -> Diff."""

from src.contracts import ScreenState
from src.parser import ANSIParser
from src.screen import apply_events, render_as_text
from src.diff import diff_screens

def run_demo():
    print("--- TermiReq Integrated Pipeline Demo ---")
    
    # Initialize
    state = ScreenState.blank(5, 20)
    before = state.snapshot()
    parser = ANSIParser()
    
    # Raw byte stream: OSC Title + Wide Char Emoji + Text
    # \x1b]0;Title\x07 (OSC 0)
    # A (1 col)
    # \xf0\x9f\x98\x8e (Emoji, 2 cols)
    data = b'\x1b]0;TermiReq Demo\x07A \xf0\x9f\x98\x8e'
    
    # Pipeline: Parser -> Screen
    events = parser.parse(data)
    apply_events(state, events)
    
    # Pipeline: Screen Diffing
    diff_result = diff_screens(before, state)
    
    # Results
    print(f"Captured Window Title: {state.title!r}")
    print("\nVirtual Screen Content:")
    for line in render_as_text(state):
        print(repr(line))
        
    print("\nDiff Report:")
    print(f"  Cursor moved: {diff_result.cursor_moved}")
    print(f"  Changes: {len(diff_result.changes)}")
    for change in diff_result.changes:
        print(f"  Row {change.row} Col {change.col}: {change.old.char!r} -> {change.new.char!r}")

if __name__ == "__main__":
    run_demo()
