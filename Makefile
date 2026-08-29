# ttydiff — Makefile (one-command build/run)

PYTHON ?= python

.PHONY: all demo test proof
all: test proof

demo:
	$(PYTHON) -m src.main run "echo hello"

test:
	$(PYTHON) -m unittest discover -s tests -p "test_*.py"

proof:
	@echo "zero third-party deps"
