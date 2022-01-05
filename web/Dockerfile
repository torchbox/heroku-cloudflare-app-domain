FROM python:3.9-slim

RUN apt-get update && apt-get install -y webhook && apt-cache purge

WORKDIR /app

COPY web/hooks.yaml /app/hooks.yaml

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py /app/

EXPOSE 9000

CMD webhook -hooks /app/hooks.yaml -template -verbose
