help:
	@echo "Available targets:"
	@echo "  install-dependencies       - Install Python dependencies in a virtual environment"
	@echo "  start-llama-server        - Start LLaMA server on port 8080"
	@echo "  llama-server-health-check - Check health of LLaMA server"
	@echo "  evaluate_MTR_embeddings   - Evaluate MTR embeddings using LLaMA server"

install-dependencies:
	@bash scripts/install-dependencies.sh

start-llama-server:
	@bash scripts/start-server.sh

llama-server-health-check:
	@curl -s http://localhost:8080/health | jq

evaluate_MTR_embeddings:
	@venv/bin/python3 eval_MTR_embeddings.py