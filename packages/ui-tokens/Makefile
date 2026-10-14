# packages/ui-tokens — общие токены дизайна (M0-INF-05). Источник — tokens.json; остальное генерируется.
SHELL := /bin/bash
.DEFAULT_GOAL := build

.PHONY: build
build: ## tokens.json → dist/{tokens.css,shadcn.css,antd.ts}, apps/crm/frontend/src/app/tokens.generated.ts, apps/cabinet/src/styles/tokens.generated.css
	node build.mjs

.PHONY: check
check: build ## Сгенерированное совпадает с закоммиченным (CI)
	git diff --exit-code -- dist ../../apps/crm/frontend/src/app/tokens.generated.ts ../../apps/cabinet/src/styles/tokens.generated.css ../../apps/erp/frontend/src/styles/tokens.generated.css \
	  || { echo "ui-tokens: dist/ или копии tokens.generated.* устарели — выполните make tokens и закоммитьте"; exit 1; }
