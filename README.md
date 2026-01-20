# automated-test-generation-2

## Docker compose commands

Create the environment

```bash
docker-compose up --build
```

Find the container ID

```bash
docker ps -a
```

Run to execute the experiment into the isolated environment

```bash
docker exec -it <container_id_ou_nome> /bin/bash
```
