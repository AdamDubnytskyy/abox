Step 1: Install virtual env

```sh
python3 -m venv venv
source venv/bin/activate
```

Step 2. Install dependencies

```sh
pip install -r requirements.txt

# verify
python3 -c "import requests; print(requests.__version__)"
```

Step 3. Run MTR embeddings evaluation script

```sh
python3 eval_MTR_embeddings.py

```