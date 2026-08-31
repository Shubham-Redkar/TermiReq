# termireq — Makefile (one-command build/run)

PYTHON ?= python

.PHONY: all build demo test proof
all: build test proof

build:
	chmod +x termireq

demo: build
	./termireq run "echo hello"

test:
	$(PYTHON) -m unittest discover -s tests -p "test_*.py"

proof:
	@echo "zero third-party deps"
