
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY main.py test_command.py fan_rules.py ./

CMD ["python", "-u", "main.py"]
