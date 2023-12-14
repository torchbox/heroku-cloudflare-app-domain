FROM python:3.11-slim

RUN apt-get update && apt-get install -y webhook && apt-get clean

WORKDIR /app

COPY docker-entrypoint.sh /app/docker-entrypoint.sh

COPY webhooks.yaml /app/webhooks.yaml

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py /app/

EXPOSE 9000

CMD /app/docker-entrypoint.sh
