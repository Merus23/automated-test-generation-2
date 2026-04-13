FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install Python 3.12, JDK, Maven and Ant
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 python3-pip \
        default-jdk maven ant && \
    rm -rf /var/lib/apt/lists/*

# Make 'python' available as an alias for python3
RUN ln -sf /usr/bin/python3 /usr/local/bin/python

COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

COPY . .

# Build the JavaParser extractor JAR
RUN cd javaparser-extractor && mvn clean package -q

# Pre-warm the Maven cache with all evaluation dependencies so the container
# works offline (e.g. on a remote machine without Maven repository access).
COPY docker/maven-warmup /tmp/maven-warmup
RUN mvn -f /tmp/maven-warmup/pom.xml -Djava.awt.headless=true test -q && \
    mvn -f /tmp/maven-warmup/pom.xml -Djava.awt.headless=true \
        org.pitest:pitest-maven:mutationCoverage -q ; \
    rm -rf /tmp/maven-warmup