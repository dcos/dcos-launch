FROM python:3.5-slim
RUN mkdir /var/run/sshd
RUN chmod 0755 /var/run/sshd
RUN apt-get update && \
    apt-get install -y libffi-dev ssh git && \
    rm -rf /var/lib/apt/lists/*
ADD . dcos-launch/
WORKDIR dcos-launch
RUN pip3 install -r requirements.txt
# use develop so you can edit in place in the docker container
RUN python3 setup.py develop
ENTRYPOINT ["dcos-launch"]
CMD ["--help"]
