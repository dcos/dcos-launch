FROM python:3.5
RUN mkdir /var/run/sshd
RUN chmod 0755 /var/run/sshd
RUN apt-get update && apt-get install -y libffi-dev ssh && apt-get install keychain
#RUN apt-get install -y unzip && \
#    wget https://releases.hashicorp.com/terraform/0.11.3/terraform_0.11.3_linux_amd64.zip && \
#    unzip terraform_0.11.3_linux_amd64.zip && \
#    mv terraform /usr/local/bin/
RUN pip3 install tox
#RUN eval `ssh-agent -s`
