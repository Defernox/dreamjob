# Equivalent Unix de dev.ps1 / setup.ps1 (make est optionnel sous Windows).
.PHONY: dev api front install migrate revision test check

install:
	cd backend && python -m venv .venv && ./.venv/Scripts/python.exe -m pip install -r requirements.txt
	cd frontend && npm install

migrate:
	cd backend && ./.venv/Scripts/alembic.exe upgrade head

# make revision m="ajout du champ X"
revision:
	cd backend && ./.venv/Scripts/alembic.exe revision --autogenerate -m "$(m)"

api:
	cd backend && ./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000

front:
	cd frontend && npm run dev

dev:
	@echo "Sous Windows, utilisez plutot : .\dev.ps1"
	$(MAKE) -j2 api front

test:
	cd backend && ./.venv/Scripts/python.exe -m pytest

check:
	cd backend && ./.venv/Scripts/python.exe -m pytest
	cd frontend && npx tsc --noEmit
