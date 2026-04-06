FROM python:3.12-slim-trixie

WORKDIR /app

# Install JDK and Maven (required by ASTJavaParser)
RUN apt-get update && \
    apt-get install -y --no-install-recommends default-jdk maven && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Build the JavaParser extractor JAR
RUN cd javaparser-extractor && mvn clean package -q