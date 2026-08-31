# Project Structure

```
TermiReq/
│
├── src/
│   ├── parser.py        # ANSI/VT100 escape sequence parser
│   ├── screen.py        # Virtual screen state management
│   ├── diff.py          # Screen diff engine
│   ├── runner.py        # Command runner with PTY handling
│   ├── cli.py           # Command line interface
│   └── main.py          # Main application entry point
│
├── tests/
│   ├── unit/
│   │   ├── test_parser.py
│   │   ├── test_screen.py
│   │   ├── test_diff.py
│   │   └── test_runner.py
│   └── integration/
│       └── test_integration.py
│
├── fixtures/            # Test fixture files
│
├── docs/
│   ├── architecture.md
│   └── api_reference.md
│
├── scripts/              # Helper scripts
│
└── configs/              # Configuration files
```

### Key Points
- All source code goes in `src/`
- Tests are organized by unit and integration
- Fixtures store test data
- Documentation lives in `docs/`
- Helper scripts in `scripts/`
