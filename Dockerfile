FROM python:3.9-slim

RUN apt-get update && apt-get install -y webhook && apt-cache purge

WORKDIR /app

COPY docker-entrypoint.sh /app/docker-entrypoint.sh

COPY webhooks.yaml /app/webhooks.yaml

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py /app/

EXPOSE 9000

CMD /app/entrypoint.sh
