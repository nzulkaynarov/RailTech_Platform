# packages/ui-tokens — общие токены дизайна (M0-INF-05). Источник — tokens.json; остальное генерируется.
SHELL := /bin/bash
.DEFAULT_GOAL := build

.PHONY: build
build: ## tokens.json → dist/{tokens.css,shadcn.css,antd.ts} и apps/crm/frontend/src/app/tokens.generated.ts
	node build.mjs

.PHONY: check
check: build ## Сгенерированное совпадает с закоммиченным (CI)
	git diff --exit-code -- dist ../../apps/crm/frontend/src/app/tokens.generated.ts \
	  || { echo "ui-tokens: dist/ или tokens.generated.ts устарели — выполните make tokens и закоммитьте"; exit 1; }
