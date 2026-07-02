# llm-eval-runner — throwaway sandbox that drives a local Ollama model through
# aider's edit->test->retry loop. Generated code only ever executes in here.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir aider-chat pytest

COPY entry.sh /usr/local/bin/entry.sh
RUN chmod +x /usr/local/bin/entry.sh

WORKDIR /work
ENTRYPOINT ["entry.sh"]
