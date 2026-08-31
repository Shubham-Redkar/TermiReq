# Common References

### File Naming Convention
- Use snake_case for all files
- Prefix test files with `test_`
- Keep fixture names descriptive

### Variable Names
- parser: `parser`
- screen: `screen`
- diff: `diff`
- runner: `runner`

### Key Functions
1. **Parser**
   - `parse(input: bytes) -> list[ParserEvent]`

2. **Screen**  
   - `apply_event(event: ParserEvent)`
   - `snapshot() -> ScreenState`

3. **Diff**
   - `diff_screens(before: ScreenState, after: ScreenState) -> DiffResult`

4. **Runner**
   - `run_commands(commands: list[str]) -> Generator[RunnerEvent]`

5. **CLI**
   - `main()`

### Shared Types
- `ParserEvent`
- `ScreenState`
- `DiffResult`
- `RunnerEvent`
