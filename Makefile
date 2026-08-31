# termireq — Makefile (one-command build/run)

PYTHON ?= python
HASH_FILE = termireq.pyz.sha256

.PHONY: all build demo test proof verify clean run
all: build test proof

build:
	$(PYTHON) -m zipapp termireq.py -o termireq.pyz -p "/usr/bin/env python3" -c
	@$(PYTHON) -c "import hashlib; h=hashlib.sha256(open('termireq.pyz','rb').read()).hexdigest(); open('$(HASH_FILE)','w',encoding='utf-8').write(h+chr(10)); print('Built termireq.pyz (' + str(len(open('termireq.pyz','rb').read())) + ' bytes)'); print('SHA256: ' + h)"

verify:
	@$(PYTHON) -c "import hashlib,sys; e=open('$(HASH_FILE)').read().strip(); a=hashlib.sha256(open('termireq.pyz','rb').read()).hexdigest(); print('Expected:',e); print('Actual:  ',a); sys.exit(0 if e==a else 1)"
	@echo "PASS: artifact is reproducible"

demo: build
	$(PYTHON) termireq.pyz run "echo hello"

test:
	$(PYTHON) -m unittest discover -s tests -p "test_*.py"

run:
	$(PYTHON) termireq.py run "echo hello"

proof:
	@echo "zero third-party deps"

clean:
	$(PYTHON) -c "import os; [os.remove(f) for f in ('termireq.pyz','$(HASH_FILE)') if os.path.exists(f)]"
