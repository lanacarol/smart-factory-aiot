"""
Worker de jobs de IA.

Consome do RabbitMQ:
- q.jobs.generate  -> roda ai/generate_dataset.py
- q.jobs.train     -> roda ai/train_models.py

Um job por vez (prefetch 1). O andamento ("Progresso: N%") e o
final do log sao publicados no exchange factory.topic com a chave
job.status.<tipo>; a API grava no PostgreSQL e mostra na interface.
"""

import json
import logging
import os
import re
import subprocess
import sys
import time

from collections import deque
from pathlib import Path

import pika


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.environ["RABBITMQ_USER"]
RABBITMQ_PASSWORD = os.environ["RABBITMQ_PASSWORD"]

AI_DIR = Path(os.getenv("AI_DIR", "/app/ai"))
EXCHANGE = "factory.topic"

QUEUES = {
    "generate": "q.jobs.generate",
    "train": "q.jobs.train",
}

PROGRESS_RE = re.compile(r"Progresso:\s*(\d+(?:\.\d+)?)%\s*(?:\|\s*(.*))?")
RESULT_PREFIX = "RESULTADO_JSON: "


def build_command(job_type, params):
    if job_type == "generate":
        return [
            sys.executable, str(AI_DIR / "generate_dataset.py"),
            "--motors", str(int(params["motors"])),
            "--cycles", str(int(params["cycles"])),
            "--seed", str(int(params["seed"])),
            "--failure-rate", str(float(params["failure_rate"])),
            "--failure-modes", ",".join(params["failure_modes"]),
            "--noise", str(float(params["noise"])),
            "--missing", str(float(params["missing_percent"])),
            "--outliers", str(float(params["outlier_percent"])),
            "--days", str(int(params["days"])),
        ]

    if job_type == "train":
        return [
            sys.executable, str(AI_DIR / "train_models.py"),
            "--max-iter", str(int(params["max_iter"])),
            "--learning-rate", str(float(params["learning_rate"])),
            "--max-leaf-nodes", str(int(params["max_leaf_nodes"])),
            "--train-rows", str(int(params["train_rows"])),
            "--window-features" if params.get("window_features", True)
            else "--no-window-features",
        ]

    raise ValueError(f"Tipo de job desconhecido: {job_type}")


def publish_status(channel, job, status, progress, message, log, result=None):
    event = {
        "event_id": f"{job['job_id']}-{time.time_ns()}",
        "device_id": "ai-jobs",
        "type": "job_status",
        "payload": {},
        "job_id": job["job_id"],
        "job_type": job["job_type"],
        "params": job.get("params", {}),
        "requested_by": job.get("requested_by"),
        "status": status,
        "progress": int(progress),
        "message": message,
        "log_tail": "\n".join(log),
        "result": result,
    }

    channel.basic_publish(
        exchange=EXCHANGE,
        routing_key=f"job.status.{job['job_type']}",
        body=json.dumps(event),
        properties=pika.BasicProperties(
            delivery_mode=2,
            content_type="application/json"
        )
    )


def run_job(connection, channel, job):
    job_type = job["job_type"]
    command = build_command(job_type, job.get("params", {}))
    log = deque(maxlen=40)

    logging.info("Iniciando job %s (%s)", job["job_id"], job_type)
    publish_status(channel, job, "running", 0, "Iniciando", log)

    process = subprocess.Popen(
        command,
        cwd=str(AI_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env={**os.environ, "PYTHONUNBUFFERED": "1"}
    )

    progress = 0
    message = "Executando"
    result = None
    last_sent = 0.0

    for line in process.stdout:
        line = line.rstrip()

        if line.startswith(RESULT_PREFIX):
            try:
                result = json.loads(line[len(RESULT_PREFIX):])
            except ValueError:
                pass
            continue

        log.append(line)
        print(line, flush=True)

        match = PROGRESS_RE.search(line)

        if match:
            progress = min(99, float(match.group(1)))
            message = match.group(2) or f"{progress:.0f}%"

        # Limita o envio de eventos e mantem o heartbeat vivo.
        now = time.monotonic()
        if match and now - last_sent > 1:
            publish_status(channel, job, "running", progress, message, log)
            last_sent = now

        connection.process_data_events(time_limit=0)

    code = process.wait()

    if code == 0:
        publish_status(channel, job, "succeeded", 100, "Concluido", log, result)
        logging.info("Job %s concluido", job["job_id"])
    else:
        last_error = next(
            (l for l in reversed(log) if l.strip()),
            "erro desconhecido"
        )
        publish_status(
            channel, job, "failed", progress,
            f"Falhou: {last_error}"[:400], log
        )
        logging.error("Job %s falhou (codigo %s)", job["job_id"], code)


def main():
    while True:
        connection = None

        try:
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=RABBITMQ_HOST,
                    credentials=pika.PlainCredentials(
                        RABBITMQ_USER,
                        RABBITMQ_PASSWORD
                    ),
                    # Treinos longos: heartbeat folgado.
                    heartbeat=600,
                    blocked_connection_timeout=300
                )
            )

            channel = connection.channel()

            channel.exchange_declare(
                exchange=EXCHANGE,
                exchange_type="topic",
                durable=True
            )

            for job_type, queue in QUEUES.items():
                channel.queue_declare(queue=queue, durable=True)
                channel.queue_bind(
                    queue=queue,
                    exchange=EXCHANGE,
                    routing_key=f"job.{job_type}"
                )

            channel.basic_qos(prefetch_count=1)

            def processar(ch, method, properties, body):
                try:
                    job = json.loads(body.decode("utf-8"))
                    if job.get("job_type") not in QUEUES or not job.get("job_id"):
                        raise ValueError("Job invalido")
                except (ValueError, UnicodeDecodeError) as error:
                    logging.warning("Mensagem de job invalida: %s", error)
                    ch.basic_nack(method.delivery_tag, requeue=False)
                    return

                try:
                    run_job(connection, ch, job)
                except Exception as error:
                    logging.exception("Erro ao executar job")
                    publish_status(
                        ch, job, "failed", 0,
                        f"Erro no worker: {error}"[:400], []
                    )

                ch.basic_ack(method.delivery_tag)

            for queue in QUEUES.values():
                channel.basic_consume(
                    queue=queue,
                    on_message_callback=processar
                )

            logging.info("Worker de IA aguardando jobs...")
            channel.start_consuming()

        except Exception as error:
            logging.warning("Worker reiniciando: %s", error)
            time.sleep(5)

        finally:
            if connection and connection.is_open:
                connection.close()


if __name__ == "__main__":
    main()
