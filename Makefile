.PHONY: install check

install:
	python3 scripts/install.py

check:
	.venv/bin/crapper --help > /dev/null
	.venv/bin/mutator --help > /dev/null
	tools/harden --help > /dev/null
	tools/lane/lane compose --help > /dev/null
	@for d in skills/*/; do name=$$(basename $$d); test -e "$$HOME/.agents/skills/$$name" || { echo "missing skill link: $$name"; exit 1; }; done
	python3 -B tools/tests/test_flow.py
	python3 -B tools/tests/test_flow_approval.py
	python3 -B tools/tests/test_progress.py
	python3 -B tools/tests/test_proof_meaningful.py
	@test -f /etc/tstack/allowed_signers || echo "warning: /etc/tstack/allowed_signers is missing, so no blocked gate can be waived. See 'One-time waiver setup' in README.md"
	@echo "check: OK"
