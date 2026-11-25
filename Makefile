.PHONY: install check

install:
	python3 scripts/install.py

check:
	.venv/bin/crapper --help > /dev/null
	.venv/bin/mutator --help > /dev/null
	tools/harden --help > /dev/null
	tools/lane/lane compose --help > /dev/null
	@for d in skills/*/; do name=$$(basename $$d); test -e "$$HOME/.agents/skills/$$name" || { echo "missing skill link: $$name"; exit 1; }; done
	@echo "check: OK"
