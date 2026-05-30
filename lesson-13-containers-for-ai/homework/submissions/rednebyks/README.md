### Metrics

| Метрика | Naive | Multi-stage |
|---|---|---|
| Image size | 1.25GB | 251MB |
| Build time | 24s | 14.2s |
| Rebuild after code change | 10.2s | 0.8s |
| Cold start (до `/health=ok`) | 1.96s | 1.6 |


## Screenshots

### Docker images (верхні 2)

![docker images](image.png)

### curl /ask

![curl /ask](image-1.png)

### docker compose ps

![docker compose ps](image-2.png)