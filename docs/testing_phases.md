# Testing Phases

## Unit Testing
1. **Parser Testing**
   - Verify proper handling of ANSI sequences
   - Check error handling for invalid input

2. **Screen Testing**
   - Validate screen state updates
   - Test cursor positioning

3. **Diff Testing**
   - Verify change detection accuracy
   - Test scroll handling

4. **Runner Testing**
   - Validate command execution
   - Test PTY handling

## Integration Testing
1. **Pipeline Testing**
   - Verify end-to-end execution
   - Test multi-command sequencing

2. **CLI Testing**
   - Validate command parsing
   - Test error handling

## Manual Testing
1. **End User Testing**
   - Clone fresh repo
   - Run sample commands
   - Verify expected output

2. **Edge Case Testing**
   - Test with long-running commands
   - Verify handling of incomplete outputs
