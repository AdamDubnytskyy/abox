# LLaMA.cpp server

Llama.cpp is a high-performance C/C++ implementation to run Large Language Models locally.


Unlike machine learning frameworks, Llama.cpp is designed to:
1. Run on consumer-grade hardware
2. Work without Python
3. Provide high-performance inference
4. Support quantized models for low memory usage


## Build llama.cpp locally


```sh

cd llms/llama.cpp
cmake -B build -DGGML_BLAS=ON -DGGML_BLAS_VENDOR=OpenBLAS
cmake --build build -j --target llama-cli llama-embedding llama-server

```

## Start server

Server configuration flags:

- `--embedding` switch server into embedding-only mode
- `--pooling mean` combines token vectors into one vector
- `-c` specifies the **maximum context size**, in tokens
- `-b` **logical maximum batch size**. Particularly important when processing multiple tokens/requests.
- `-ub` **physical batch size** used by the underlying computation



Start `llama.cpp's` HTTP server, load `Nomic Embed Text` v1.5 using the `Q4_K_M` quantized model, operate exclusively as an embedding server, combine token representations using mean pooling, allow up to 2048 tokens of context, and process computation in batches of up to 512 tokens.

```sh
./build/bin/llama-server \
  -hf nomic-ai/nomic-embed-text-v1.5-GGUF:Q4_K_M \
  --embedding \
  --pooling mean \
  -c 8192 \
  -b 512 \
  -ub 512
```

Verify `llama-server` is running:

```sh
ss -tnlp | grep llama
LISTEN 0      512             127.0.0.1:8080       0.0.0.0:*    users:(("llama-server",pid=288909,fd=3))
```

## Usage

```sh
curl http://localhost:8080/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nomic-embed-text-v1.5",
    "input": "search_query: test"
  }'
```
