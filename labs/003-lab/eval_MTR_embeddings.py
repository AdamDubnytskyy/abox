import requests
import math

SERVER_URL = "http://localhost:8080/v1/embeddings"
DIM_TRUNCATED = 256
DIM_FULL = 768


def get_embedding(text: str) -> list[float]:
    resp = requests.post(
        SERVER_URL,
        json={"model": "nomic-embed-text-v1.5", "input": text}
    )
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]


def truncate_and_normalize(vec: list[float], dim: int) -> list[float]:
    truncated = vec[:dim]
    norm = math.sqrt(sum(x * x for x in truncated))
    return [x / norm for x in truncated]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


# По одній тестовій трійці на кожен із 5 сценаріїв.
# query      -> що запитує агент
# relevant   -> фрагмент, який МАЄ бути знайдений як релевантний
# irrelevant -> фрагмент з тієї ж предметної області, але не по темі запиту
scenarios = {
    "1_health_check_metrics": {
        "query": "search_query: чи все гаразд з кластером зараз?",
        "relevant": "search_document: node-3 CPU usage 92% for last 15m, memory pressure detected, kubelet reporting DiskPressure condition True",
        "irrelevant": "search_document: Deployment frontend-web scaled from 3 to 5 replicas via HPA at 14:02 UTC",
    },
    "2_resource_tuning": {
        "query": "search_query: як налаштувати resource requests для сервісу payments-api в неймспейсі payments?",
        "relevant": "search_document: payments-api container actual usage over 7d: CPU p95 180m, memory p95 340Mi, current requests: CPU 500m, memory 512Mi — over-provisioned",
        "irrelevant": "search_document: NetworkPolicy default-deny applied to namespace payments, ingress restricted to gateway namespace",
    },
    "3_events_incident": {
        "query": "search_query: чому pod у namespace payments постійно рестартиться?",
        "relevant": "search_document: Event: Warning BackOff pod payments-7f9c OOMKilled, restart count 12",
        "irrelevant": "search_document: ClusterRole binding updated for service-account monitoring-agent",
    },
    "4_proactive_risk": {
        "query": "search_query: де в кластері потенційно можуть виникнути проблеми найближчим часом?",
        "relevant": "search_document: PersistentVolume storage-logs-01 usage at 87% and growing ~2%/day, no autoscaling configured for underlying storage class",
        "irrelevant": "search_document: ConfigMap app-config updated with new feature flag rollout-v2-enabled=true",
    },
    "5_security_upgrade": {
        "query": "search_query: що потрібно оновити з точки зору безпеки в кластері?",
        "relevant": "search_document: Ingress-nginx controller running version 1.9.3, CVE-2024-7646 affects versions < 1.10.1, upgrade recommended",
        "irrelevant": "search_document: HorizontalPodAutoscaler for orders-service min replicas 2 max replicas 10 target CPU 70%",
    },
}

results = []

for name, texts in scenarios.items():
    vecs_trunc = {}
    vecs_full = {}

    for label, text in texts.items():
        full_vec = get_embedding(text)
        vecs_trunc[label] = truncate_and_normalize(full_vec, DIM_TRUNCATED)
        vecs_full[label] = truncate_and_normalize(full_vec, DIM_FULL)

    sim_rel_trunc = cosine(vecs_trunc["query"], vecs_trunc["relevant"])
    sim_irr_trunc = cosine(vecs_trunc["query"], vecs_trunc["irrelevant"])
    gap_trunc = sim_rel_trunc - sim_irr_trunc

    sim_rel_full = cosine(vecs_full["query"], vecs_full["relevant"])
    sim_irr_full = cosine(vecs_full["query"], vecs_full["irrelevant"])
    gap_full = sim_rel_full - sim_irr_full

    ranking_ok = sim_rel_trunc > sim_irr_trunc
    retained_pct = (gap_trunc / gap_full * 100) if gap_full != 0 else float("nan")

    results.append({
        "scenario": name,
        "gap_256": gap_trunc,
        "gap_768": gap_full,
        "retained_pct": retained_pct,
        "ranking_ok": ranking_ok,
    })

    status = "OK" if ranking_ok else "FAIL"
    print(f"[{status}] {name}")
    print(f"    256: relevant={sim_rel_trunc:.4f}  irrelevant={sim_irr_trunc:.4f}  gap={gap_trunc:.4f}")
    print(f"    768: relevant={sim_rel_full:.4f}  irrelevant={sim_irr_full:.4f}  gap={gap_full:.4f}")
    print(f"    збережено розрізняльної здатності на 256: {retained_pct:.1f}%")
    print()

# Підсумок по всіх сценаріях
avg_retained = sum(r["retained_pct"] for r in results) / len(results)
all_ranking_ok = all(r["ranking_ok"] for r in results)
worst = min(results, key=lambda r: r["retained_pct"])

print("=" * 60)
print("ПІДСУМОК")
print(f"Усі сценарії з коректним ранжуванням на 256: {'так' if all_ranking_ok else 'НІ — див. FAIL вище'}")
print(f"Середньо збережено розрізняльної здатності на 256: {avg_retained:.1f}%")
print(f"Найгірший сценарій: {worst['scenario']} ({worst['retained_pct']:.1f}%)")