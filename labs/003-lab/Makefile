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

NAMESPACE ?= clusterobserver-demo
MANIFEST  ?= k8s/001-deployment.yaml

.PHONY: provision-sidecar
provision-sidecar:
	@echo ">> applying $(MANIFEST) to current kubectl context"
	kubectl apply -f $(MANIFEST)
	kubectl rollout status deployment/embedding-sidecar-demo -n $(NAMESPACE) --timeout=300s

.PHONY: test-sidecar
test-sidecar: ## Call the embedding sidecar from inside the demo pod to verify it works
	kubectl exec -n $(NAMESPACE) deploy/embedding-sidecar-demo -c app -- \
		curl -s -X POST http://localhost:8080/v1/embeddings \
		-H "Content-Type: application/json" \
		-d '{"model": "nomic-embed-text-v1.5", "input": "search_query: is the sidecar alive?"}'

.PHONY: teardown-sidecar
teardown-sidecar: ## Remove the sidecar demo deployment and namespace
	kubectl delete -f $(MANIFEST) --ignore-not-found
