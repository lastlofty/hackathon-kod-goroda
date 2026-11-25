.PHONY: dev gpu test logs stop gpu-stop

dev:
	INFERENCE_MODE=mock docker compose -f docker-compose.yml up -d --build

gpu:
	docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build

test:
	python -m pytest -q

logs:
	docker compose -f docker-compose.yml logs -f

stop:
	docker compose -f docker-compose.yml down

gpu-stop:
	docker compose -f docker-compose.yml -f docker-compose.gpu.yml down
