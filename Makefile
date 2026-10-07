.PHONY: build test build-app build-ui build-image build-tf \
        test-python test-frontend test-tf \
        lint fmt tf-fmt tf-plan clean

build: build-app build-ui build-tf

test: test-python test-frontend test-tf

## apps

build-app:
	uv build

build-ui:
	cd ui && npm ci && npm run build

build-image:
	docker build -t fuel-backend:local -f backend/Dockerfile .

test-python:
	pip install -q fastapi uvicorn httpx pytest pytest-asyncio pydantic
	python -m pytest

test-frontend:
	cd ui && npm ci && npm test

lint:
	uv run ruff check garmin_mcp.py
	uv run ruff format --check garmin_mcp.py

fmt:
	uv run ruff format garmin_mcp.py

## terraform (two independent roots: terraform/ = fuel stack, iam/ = fuel_terraform role)

build-tf:
	cd terraform && tofu init -backend=false -input=false && tofu validate
	cd iam && tofu init -backend=false -input=false && tofu validate

test-tf: build-tf

tf-fmt:
	tofu fmt -recursive terraform iam

# Real plan/apply needs cloud credentials (human for iam/, WIF SA in CI for
# terraform/ — see iam/README.md) and isn't part of build/test.
tf-plan:
	cd terraform && tofu init -input=false && tofu plan

clean:
	rm -rf .pytest_cache .ruff_cache __pycache__ ui/dist

tf-plan-iam:
	cd iam && tofu init -input=false && tofu plan

tf-apply-iam:
	cd iam && tofu init -input=false && tofu apply