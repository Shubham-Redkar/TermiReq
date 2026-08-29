# Siddhesh's Tasks

### Parser & Screen Development
1. **T2:** Build parser core
   - Implement byte scanner
   - Handle cursor movement codes
   - Process plain character printing
   - Track byte-offset and line-col positions

2. **T2b:** Extend parser functionality
   - Add support for erase codes (ED/EL)
   - Implement SGR color codes

3. **T3:** Develop virtual screen grid
   - Create grid model for terminal screen
   - Track cursor position
   - Maintain cell contents

### Key Deliverables
- Stable parser that handles basic terminal commands
- Virtual screen model that accurately represents terminal state
- Documentation of parser limitations in STDLIB.md

### Timeline
- Day 1: Complete T2 and start T2b
- Day 2: Complete T3 and integrate with runner
- Day 3: Final testing and documentation
