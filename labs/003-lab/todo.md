# Development

Step 1. Install dependencies

```sh
make install-dependencies
```

Step 2. Start LLaMA server

```sh
make start-llama-server
```

[See details how to start LLaMA server](https://github.com/AdamDubnytskyy/abox/blob/main/labs/003-lab/llama-server.md#start-server)

Step 3: Run MTR embeddings evaluation script

```sh
make evaluate_MTR_embeddings
```

---

# Production

Step 1. Deploy embedding-sidecar-demo

```sh
make provision-sidecar
```

Step 2. Call the embedding sidecar from inside the demo pod to verify it works

```sh
make test-sidecar
```